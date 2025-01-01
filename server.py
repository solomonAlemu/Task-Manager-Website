from flask import Flask, render_template, request, redirect, url_for, jsonify, session
from apscheduler.schedulers.background import BackgroundScheduler
from flask import Flask
import atexit
import sqlite3
import os
from datetime  import datetime, timedelta  # Import timedelta
import json
import bcrypt
import re
import pandas as pd  # Import pandas to handle Excel/CSV files
import secrets  
import socket
import platform
import subprocess
from email_config import EmailManager
from email_sender import EmailNotifier
from user_management import UserApp
from waitress import serve
from flask import send_file
import csv
from io import StringIO
from io import BytesIO, TextIOWrapper
from flask import flash
from pandas.core.arrays import integer

# Initialize Flask app
app = Flask(__name__)
DATABASE = 'tasks.db'
app.secret_key = os.environ.get('SECRET_KEY', 'your_very_secret_key_here')

# Define cleanup function
def cleanup_expired_tokens():
    """
    Cleans up expired password reset tokens from the database.
    This function removes tokens that have expired and are no longer valid.
    """
    try:
        with get_db_connection() as conn:
            cursor = conn.cursor()
            # Delete tokens that are expired (where expires_at < current time)
            cursor.execute('''DELETE FROM password_reset_tokens WHERE expires_at <= ?''', (datetime.now(),))
            conn.commit()
            print(f"Expired tokens cleaned up successfully at {datetime.now()}.")
    except sqlite3.Error as e:
        print(f"Database error in cleanup_expired_tokens: {e}")

# Database connection function
def get_db_connection():
    """Establish a connection to the database."""
    conn = sqlite3.connect(DATABASE)
    conn.row_factory = sqlite3.Row  # Return results as dictionaries
    return conn

def init_db():
    """Initialize the database and create tables if they don't exist."""
    with sqlite3.connect(DATABASE) as conn:
        cursor = conn.cursor()

        # User roles table (no change)
        cursor.execute('''
        CREATE TABLE IF NOT EXISTS user_roles (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            role_name TEXT NOT NULL UNIQUE,
            role_level INTEGER NOT NULL,
            can_approve_from INTEGER,
            reports_to INTEGER,
            FOREIGN KEY(can_approve_from) REFERENCES user_roles(id),
            FOREIGN KEY(reports_to) REFERENCES user_roles(id)
        )
        ''')

        # Insert default roles if they don't exist
        cursor.execute('''
            INSERT OR IGNORE INTO user_roles (role_name, role_level, reports_to) 
            VALUES 
                ('Managing Director', 1, NULL),
                ('Acting Managing Director', 1, NULL),
                ('Director', 2, 1),
                ('Acting Director', 2, 1),
                ('Manager', 3, 2),
                ('Acting Manager', 3, 2),
                ('Team Leader', 4, 3),
                ('Acting Team Leader', 4, 3),
                ('ACE Agent', 5, 4),
                ('ACE Co-Agent', 5, 4),       
                ('Employee', 6, 5); 
        ''')

        # Create users table with department column
        cursor.execute('''
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT UNIQUE NOT NULL,
            email TEXT UNIQUE NOT NULL,
            password_hash TEXT NOT NULL,
            created_at TEXT DEFAULT (DATETIME('now', 'localtime')),
            last_login TEXT DEFAULT NULL,
            is_active INTEGER DEFAULT 1,
            role TEXT DEFAULT 'Employee',
            department TEXT,
            FOREIGN KEY(role) REFERENCES user_roles(role_name)
        )
        ''')

        # Password reset tokens table
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

        # Monthly action items table
        cursor.execute('''
        CREATE TABLE IF NOT EXISTS monthly_action_items (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            description TEXT NOT NULL,
            target_value REAL,
            current_value REAL DEFAULT 0,           
            priority TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'Open',
            due_date TEXT DEFAULT NULL,
            notes TEXT DEFAULT '',
            percentage_completion INTEGER DEFAULT 0 CHECK(percentage_completion BETWEEN 0 AND 100),
            created_at TEXT DEFAULT (DATETIME('now', 'localtime')),
            semi_annual_plan_id INTEGER,
            target_portion REAL DEFAULT 0,
            FOREIGN KEY(semi_annual_plan_id) REFERENCES semi_annual_plans(id) ON DELETE CASCADE,
            FOREIGN KEY(user_id) REFERENCES users(id)
        )
        ''')

        # Semi-annual plans table (no change)
        cursor.execute('''
        CREATE TABLE IF NOT EXISTS semi_annual_plans (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            title TEXT NOT NULL,
            description TEXT NOT NULL,
            target_value REAL,
            current_value REAL DEFAULT 0,
            start_date TEXT NOT NULL,
            end_date TEXT NOT NULL,
            priority TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'Open',
            notes TEXT DEFAULT '',
            percentage_completion INTEGER DEFAULT 0 CHECK(percentage_completion BETWEEN 0 AND 100),
            created_at TEXT DEFAULT (DATETIME('now', 'localtime')),
            FOREIGN KEY(user_id) REFERENCES users(id)
        )
        ''')

        # Tasks table with `portion` column
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
            portion REAL DEFAULT 0,
            created_at TEXT DEFAULT (DATETIME('now', 'localtime')),
            assigned_by INTEGER,
            requires_approval INTEGER DEFAULT 0,
            approved_by INTEGER DEFAULT NULL,
            approval_status TEXT DEFAULT 'Pending',
            FOREIGN KEY(user_id) REFERENCES users(id),
            FOREIGN KEY(monthly_action_id) REFERENCES monthly_action_items(id) ON DELETE CASCADE,
            FOREIGN KEY(assigned_by) REFERENCES users(id),
            FOREIGN KEY(approved_by) REFERENCES users(id)
        )
        ''')
        # Trigger to update monthly action plan progress (no change)
        cursor.execute('''
        CREATE TRIGGER IF NOT EXISTS update_monthly_action_progress
        AFTER UPDATE ON tasks
        WHEN NEW.status = 'Completed' AND OLD.status != 'Completed'
        BEGIN
            UPDATE monthly_action_items
            SET current_value = (
                SELECT COALESCE(SUM(portion), 0)
                FROM tasks
                WHERE monthly_action_id = NEW.monthly_action_id
                AND status = 'Completed'
            ),
            percentage_completion = (
                SELECT ROUND(COALESCE(SUM(portion), 0) * 100.0 / target_portion)
                FROM tasks
                WHERE monthly_action_id = NEW.monthly_action_id
                AND status = 'Completed'
            )
            WHERE id = NEW.monthly_action_id;

            UPDATE monthly_action_items
            SET status = 'Completed'
            WHERE id = NEW.monthly_action_id
            AND current_value >= target_portion;
        END;
        ''')
        cursor.execute('''
        CREATE TRIGGER IF NOT EXISTS update_semi_annual_plan_progress
        AFTER UPDATE ON monthly_action_items
        WHEN NEW.status = 'Completed' AND OLD.status != 'Completed'
        BEGIN
            UPDATE semi_annual_plans
            SET current_value = (
                SELECT COALESCE(SUM(target_portion), 0)
                FROM monthly_action_items
                WHERE semi_annual_plan_id = NEW.semi_annual_plan_id
                AND status = 'Completed'
            ),
            percentage_completion = (
                SELECT ROUND(COALESCE(SUM(target_portion), 0) * 100.0 / target_value)
                FROM monthly_action_items
                WHERE semi_annual_plan_id = NEW.semi_annual_plan_id
                AND status = 'Completed'
            )
            WHERE id = NEW.semi_annual_plan_id;

            -- Auto-complete semi-annual plan if target is reached
            UPDATE semi_annual_plans
            SET status = 'Completed'
            WHERE id = NEW.semi_annual_plan_id
            AND current_value >= target_value;
        END;
        ''')
        
        # Commit all changes
        conn.commit()

# Initialize the database if not already done
if not os.path.exists(DATABASE):
    init_db()

# Initialize email manager and other components (you can add your components here)
email_manager = EmailManager()
email_notifier = EmailNotifier()

# Initialize APScheduler
scheduler = BackgroundScheduler()

# Add job to run the cleanup_expired_tokens function every hour
scheduler.add_job(func=cleanup_expired_tokens, trigger='interval', hours=1)

# Start the scheduler
scheduler.start()

def get_user_role(user_id):
    """Get the role of a user."""
    with get_db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute('SELECT role FROM users WHERE id = ?', (user_id,))
        result = cursor.fetchone()
        return result[0] if result else None

def can_approve_task(approver_id, task_id):
    """Check if a user can approve a task."""
    with get_db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute('''
            SELECT u1.role as approver_role, u2.role as assignee_role
            FROM users u1, users u2, tasks t
            WHERE u1.id = ? AND u2.id = t.user_id AND t.id = ?
        ''', (approver_id, task_id))
        roles = cursor.fetchone()
        if not roles:
            return False
        
        # Check role hierarchy
        cursor.execute('''
            SELECT r1.role_level < r2.role_level
            FROM user_roles r1, user_roles r2
            WHERE r1.role_name = ? AND r2.role_name = ?
        ''', (roles[0], roles[1]))
        return cursor.fetchone()[0]

# Add this template context processor
@app.context_processor
def utility_processor():
    return {
        'current_user_can_approve': lambda task_id: can_approve_task(session.get('user_id'), task_id),
        'get_user_role': lambda user_id: get_user_role(user_id)
    }
 
@app.route('/')
def home():
    """Render the home page with tasks and monthly action items for the logged-in user."""
    if 'user_id' not in session:
        return redirect(url_for('login'))

    user_id = session['user_id']  # Get logged-in user's ID

    try:
        with get_db_connection() as conn:
            cursor = conn.cursor()

            # Fetch the username of the current user
            cursor.execute('SELECT username FROM users WHERE id = ?', (user_id,))
            current_username = cursor.fetchone()['username']

            # Fetch tasks for the logged-in user
            cursor.execute("""
                SELECT 
                    tasks.id, tasks.assigned_person, tasks.description, tasks.priority, tasks.status,
                    tasks.percentage_completion, tasks.notes, tasks.updates, tasks.due_date,
                    tasks.assigned_by, tasks.approval_status, tasks.approved_by,
                    monthly_action_items.description AS monthly_action_description,
                    u.username AS assigned_by_name, 
                    ua.username AS approved_by_name,
                    tasks.requires_approval
                FROM tasks
                LEFT JOIN users u ON tasks.assigned_by = u.id
                LEFT JOIN users ua ON tasks.approved_by = ua.id
                LEFT JOIN monthly_action_items ON tasks.monthly_action_id = monthly_action_items.id
                WHERE (tasks.user_id = ? OR tasks.assigned_by = ? OR tasks.assigned_person = ? OR tasks.approved_by = ?)
                AND NOT (
                    tasks.status IN ('Completed', 'Cancelled') 
                    AND tasks.approval_status IN ('Approved!', 'Rejected!') 
                    AND tasks.percentage_completion = 100
                )
            """, (user_id, user_id, current_username, user_id))

            tasks = cursor.fetchall()

            # Fetch monthly action items for task creation dropdown
            cursor.execute("""
                SELECT id, description, priority, current_value, target_portion 
                FROM monthly_action_items 
                WHERE user_id = ? AND status IN ('Open', 'In Progress')
            """, (user_id,))
            monthly_actions = cursor.fetchall()
        return render_template('Home.html', tasks=tasks, monthly_actions=monthly_actions, current_user=current_username)
    except sqlite3.Error as e:
        print(f"Database error: {e}")
        return f"An error occurred: {e}", 500


# Add these new routes to server.py
@app.route('/assign-task', methods=['POST'])
def assign_task():
    if 'user_id' not in session:
        return jsonify({"success": False, "error": "Unauthorized"}), 401
    
    assigner_id = session['user_id']
    assignee_id = request.form.get('assignee_id')
    description = request.form.get('description')
    priority = request.form.get('priority', 'Medium')
    due_date = request.form.get('due_date')
    
    try:
        with get_db_connection() as conn:
            cursor = conn.cursor()
            
            # Get assigner's role
            cursor.execute('''
                SELECT role FROM users WHERE id = ?
            ''', (assigner_id,))
            assigner_role = cursor.fetchone()[0]
            
            # Get assignee's role
            cursor.execute('''
                SELECT role FROM users WHERE id = ?
            ''', (assignee_id,))
            assignee_role = cursor.fetchone()[0]
            
            # Check if assignment is allowed based on hierarchy
            cursor.execute('''
                SELECT r1.role_level as assigner_level, r2.role_level as assignee_level
                FROM user_roles r1, user_roles r2
                WHERE r1.role_name = ? AND r2.role_name = ?
            ''', (assigner_role, assignee_role))
            
            levels = cursor.fetchone()
            if not levels or levels[0] >= levels[1]:
                return jsonify({"success": False, "error": "Invalid task assignment hierarchy"}), 403
            
            # Create the task
            cursor.execute('''
                INSERT INTO tasks (
                    user_id, assigned_person, description, priority, 
                    due_date, assigned_by, requires_approval
                ) VALUES (?, ?, ?, ?, ?, ?, 1)
            ''', (assignee_id, request.form.get('assigned_person'), description, 
                 priority, due_date, assigner_id))
            
            conn.commit()
            return jsonify({"success": True, "message": "Task assigned successfully"})
            
    except sqlite3.Error as e:
        print(f"Database error: {e}")
        return jsonify({"success": False, "error": "Database error"}), 500

@app.route('/add', methods=['POST'])
def add_task():
    """Add a new task with optional monthly action item link."""
    if 'user_id' not in session:
        flash("Unauthorized access. Please log in.", "error")
        return redirect(url_for('login'))

    user_id = session['user_id']
    description = request.form.get('description', '').strip()
    try:
        portion = float(request.form.get('portion', 0))
    except ValueError:
        portion = 0
    priority = request.form.get('priority', 'Medium')
    due_date = request.form.get('due_date', '').strip()
    monthly_action_id = request.form.get('monthly_action_id')
    recipients = request.form.get('recipients', '[]')

    try:
        recipients = json.loads(recipients)
    except json.JSONDecodeError:
        recipients = []

    if not description:
        flash("Description is required.", "error")
        return redirect(url_for('home'))
       
    try:
        with get_db_connection() as conn:
            cursor = conn.cursor()
            if not recipients: 
                   cursor.execute("SELECT username FROM users WHERE id = ?", (user_id,))
                   assigned_person = cursor.fetchone()['username']
                   recipients = [{"name": assigned_person}]
                       
            for recipient in recipients:
                assigned_person = recipient['name']
                
                # Retrieve assignee_id from assigned_person reference
                cursor.execute("SELECT id FROM users WHERE username = ?", (assigned_person,))
                assignee_row = cursor.fetchone()
                if not assignee_row:
                    flash(f"Error: Assigned person '{assigned_person}' not found!", "error")
                    continue
                assignee_id = assignee_row[0]

                # Validate portion against monthly action target if provided
                if monthly_action_id:
                    cursor.execute("""
                        SELECT ma.target_portion,
                               (SELECT COALESCE(SUM(portion), 0)
                                FROM tasks
                                WHERE monthly_action_id = ?) as allocated_portions
                        FROM monthly_action_items ma
                        WHERE ma.id = ?
                    """, (monthly_action_id, monthly_action_id))
                    
                    action_data = cursor.fetchone()
                    if action_data:
                        total_target = action_data[0] or 0
                        allocated = action_data[1] or 0
                        remaining = total_target - allocated

                        if portion > remaining:
                            flash(f"Error: Portion ({portion}) exceeds remaining target ({remaining}) for '{assigned_person}'.", "error")
                            continue

                # Check task assignment hierarchy
                cursor.execute("SELECT role FROM users WHERE id = ?", (user_id,))
                assigner_role = cursor.fetchone()[0]

                cursor.execute("SELECT role FROM users WHERE id = ?", (assignee_id,))
                assignee_role = cursor.fetchone()[0]

                cursor.execute("""
                    SELECT r1.role_level as assigner_level, r2.role_level as assignee_level
                    FROM user_roles r1, user_roles r2
                    WHERE r1.role_name = ? AND r2.role_name = ?
                """, (assigner_role, assignee_role))
                
                levels = cursor.fetchone()
                if not levels or levels[0] > levels[1]:
                    flash(f"Error: Invalid task assignment hierarchy for '{assigned_person}'.", "error")
                    continue

                # Insert the task
                cursor.execute("""
                    INSERT INTO tasks (
                        user_id, assigned_person, description, priority, due_date, portion,
                        status, monthly_action_id, assigned_by, requires_approval, approved_by
                    ) VALUES (?, ?, ?, ?, ?, ?, 'Open', ?, ?, ?, ?)
                """, (
                    assignee_id,
                    assigned_person,
                    description,
                    priority,
                    due_date,
                    portion,
                    monthly_action_id,
                    user_id,
                    1,
                    user_id
                ))

                # Update monthly action progress
                if monthly_action_id:
                    cursor.execute("""
                        UPDATE monthly_action_items
                        SET current_value = (
                            SELECT COALESCE(SUM(portion), 0)
                            FROM tasks
                            WHERE monthly_action_id = ?
                        ),
                        percentage_completion = (
                            SELECT ROUND(COALESCE(SUM(portion), 0) * 100.0 / target_portion)
                            FROM tasks
                            WHERE monthly_action_id = ? AND status = 'Completed'
                        )
                        WHERE id = ?
                    """, (monthly_action_id, monthly_action_id, monthly_action_id))

            conn.commit()
            flash('Tasks added successfully!', 'success')
            return redirect(url_for('home'))

    except sqlite3.Error as e:
        flash(f"Error: {e}", "error")
        return redirect(url_for('home'))

@app.route('/approve-task/<int:task_id>', methods=['POST'])
def approve_task(task_id):
    """Approve or reject an approval request for a task from the task assigner."""
    if 'user_id' not in session:
        flash("Unauthorized: Please log in to approve or reject tasks.", "error")
        return redirect(url_for('login'))

    approval_status = request.form.get('status')  # 'approved' or 'rejected'

    try:
        with get_db_connection() as conn:
            cursor = conn.cursor()

            # Fetch task details
            cursor.execute('''
                SELECT assigned_by, approved_by
                FROM tasks
                WHERE id = ?
            ''', (task_id,))
            
            task = cursor.fetchone()
            if not task:
                flash("Error: Task not found.", "error")
                return redirect(url_for('home'))

            assigned_by = task[0]
            approved_by = task[1]
            approver_id = session['user_id']

            # Determine final approval status
            if approved_by == approver_id:
                final_approval_status = approval_status
            else:
                final_approval_status = "Pending (" + approval_status + ")"

            # Set additional fields if the task is approved
            if approval_status.lower() == 'Approved!':
                task_status = 'Completed'
                percentage_completion = 100
            else:
                task_status = None
                percentage_completion = None

            # Update task approval status and potentially other fields
            if task_status and percentage_completion is not None:
                cursor.execute('''
                    UPDATE tasks 
                    SET approval_status = ?, status = ?, percentage_completion = ?
                    WHERE id = ?
                ''', (final_approval_status, task_status, percentage_completion, task_id))
            else:
                cursor.execute('''
                    UPDATE tasks 
                    SET approval_status = ?
                    WHERE id = ?
                ''', (final_approval_status, task_id))

            conn.commit()
            flash(f"Task {approval_status}.", "success")
            return redirect(url_for('home'))
            
    except sqlite3.Error as e:
        print(f"Database error: {e}")
        flash("Error: Database error occurred.", "error")
        return redirect(url_for('home'))

@app.route('/request_approval/<int:task_id>', methods=['POST'])
def request_approval(task_id):
    """Request approval for a task from the task assigner or approver."""
    if 'user_id' not in session:
        flash("Unauthorized: Please log in to request a status update.", "error")
        return redirect(url_for('login'))

    user_id = session['user_id']
    try:
        with get_db_connection() as conn:
            cursor = conn.cursor()

            # Fetch the username of the current user
            cursor.execute('SELECT username FROM users WHERE id = ?', (user_id,))
            current_username = cursor.fetchone()['username']

            # Verify that the task is assigned to the current user
            cursor.execute('''
                SELECT id, assigned_by, approved_by
                FROM tasks
                WHERE id = ? AND assigned_person = ?
            ''', (task_id, current_username))
            task = cursor.fetchone()

            if not task:
                flash("Error: Task not found or you do not have permission to request an update.", "error")
                return redirect(url_for('home'))

            assigned_by = task[1]
            approved_by = task[2]

            # Set approval status to "Requesting approval"
            cursor.execute('''
                UPDATE tasks
                SET approval_status = 'Requesting approval', requires_approval = 1
                WHERE id = ?
            ''', (task_id,))
            conn.commit()

            flash("Approval request sent to the task assigner or approver.", "success")
        return redirect(url_for('home'))
    except sqlite3.Error as e:
        print(f"Database error: {e}")
        flash("Error: Unable to send approval request.", "error")
        return redirect(url_for('home'))

@app.route('/request-status-update/<int:task_id>', methods=['POST'])
def request_status_update(task_id):
    """Request a status update for a specific task from the task assigner or reassigner."""

    if 'user_id' not in session:
        flash("Unauthorized: Please log in to request a status update.", "error")
        return redirect(url_for('login'))
    
    approver_id = session['user_id']
    approval_status = "Status Update Required"
    
    try:
        with get_db_connection() as conn:
            cursor = conn.cursor()
            
            # Check if the logged-in user is the task assigner or reassigner
            cursor.execute('''
                SELECT id, assigned_by, approved_by
                FROM tasks
                WHERE id = ? AND (assigned_by = ? OR approved_by = ?)
            ''', (task_id, approver_id, approver_id))
            
            task = cursor.fetchone()

            if not task:
                flash("Error: Task not found or you do not have permission to approve/reject it.", "error")
                return redirect(url_for('home'))

            approved_by = task[2]  # Retain the original approver ID

            # Update the task to indicate a status update request
            cursor.execute('''
                UPDATE tasks 
                SET approval_status = ?
                WHERE id = ?
            ''', (approval_status, task_id))
            
            conn.commit()

            flash("Status update request sent to the task assignee.", "success")
        return redirect(url_for('home'))
    except sqlite3.Error as e:
        print(f"Database error: {e}")
        flash("Error: Unable to send status update request.", "error")
        return redirect(url_for('home'))

@app.route('/request_justification/<int:task_id>', methods=['POST'])
def request_justification(task_id):
    """Request a status update for a specific task from the task assigner or reassigner."""

    if 'user_id' not in session:
        flash("Unauthorized: Please log in to request a status update.", "error")
        return redirect(url_for('login'))
    
    approver_id = session['user_id']
    approval_status = "Justification Required"
    
    try:
        with get_db_connection() as conn:
            cursor = conn.cursor()
            
            # Check if the logged-in user is the task assigner or reassigner
            cursor.execute('''
                SELECT id, assigned_by, approved_by
                FROM tasks
                WHERE id = ? AND (assigned_by = ? OR approved_by = ?)
            ''', (task_id, approver_id, approver_id))
            
            task = cursor.fetchone()

            if not task:
                flash("Error: Task not found or you do not have permission to approve/reject it.", "error")
                return redirect(url_for('home'))

            approved_by = task[2]  # Retain the original approver ID

            # Update the task to indicate a status update request
            cursor.execute('''
                UPDATE tasks 
                SET approval_status = ?
                WHERE id = ?
            ''', (approval_status, task_id))
            
            conn.commit()

            flash("Status update request sent to the task assignee.", "success")
        return redirect(url_for('home'))
    except sqlite3.Error as e:
        print(f"Database error: {e}")
        flash("Error: Unable to send status update request.", "error")
        return redirect(url_for('home'))
    
@app.route('/update/<int:task_id>', methods=['POST'])
def update_task(task_id):
    """Update task details for the logged-in user."""
    if 'user_id' not in session:
        flash("Unauthorized access. Please log in.", "error")
        return redirect(url_for('login'))

    user_id = session['user_id']
    status = request.form.get('status', 'Open')
    percentage_completion = request.form.get('percentage_completion')
    notes = request.form.get('notes', '').strip()
    description = request.form.get('revised_description', '').strip()
    priority = request.form.get('priority', 'Medium')
    due_date = request.form.get('due_date', '').strip()
    portion = request.form.get('portion', 0)
    monthly_action_id = request.form.get('monthly_action_id')
    recipients = request.form.get('recipients', '[]')  # Get recipients JSON

    try:
        portion = float(portion) if portion else 0
    except ValueError:
        portion = 0

    # Parse recipients
    try:
        recipients = json.loads(recipients)
        # Convert the list of names into a comma-separated string
        assigned_person = ", ".join(recipient['name'] for recipient in recipients)
    except json.JSONDecodeError:
        assigned_person = ""

    if percentage_completion:
        try:
            percentage_completion = int(percentage_completion)
        except ValueError:
            percentage_completion = None
    else:
        percentage_completion = None

    try:

        with get_db_connection() as conn:
            cursor = conn.cursor()

            # Fetch user role
            cursor.execute("SELECT role FROM users WHERE id = ?", (user_id,))
            user_role = cursor.fetchone()['role']

            # Prevent task reassignment if user role is 'Employee'
            if user_role == 'Employee' and assigned_person:
                flash("You do not have permission to reassign tasks.", "error")
                return redirect(url_for('home'))

            # Fetch the existing task
            cursor.execute("""
                SELECT assigned_person, description, priority, status, percentage_completion, 
                       updates, due_date, monthly_action_id, approved_by, approval_status, 
                       assigned_by, portion
                FROM tasks
                WHERE id = ? AND (user_id = ? OR assigned_by = ? OR approved_by = ? OR assigned_person = (
                    SELECT username FROM users WHERE id = ?
                ))
            """, (task_id, user_id, user_id, user_id, user_id))
            task = cursor.fetchone()

            if not task:
                flash("Error: Task not found or unauthorized.", "error")
                return redirect(url_for('home'))

            current_assigned_person, current_description, current_priority, current_status, \
            current_percentage, current_updates, current_due_date, current_monthly_action_id, \
            current_approved_by, current_approval_status, current_assigned_by, current_portion = task


            # Append new notes to updates
            update_entry = (
                (current_updates or "") +
                f"\n\n== Update ({datetime.now().strftime('%Y-%m-%d %H:%M')})\n"
                f"{notes or 'No notes'} | Status: {status}\n"
            )

            # Maintain current values if fields are not provided
            if not assigned_person:
                assigned_person = current_assigned_person
            if not description:
                description = current_description
            if status == "Open" or not status:
                status = current_status
            if percentage_completion == 0:
                percentage_completion = current_percentage
                status = current_status
            if not priority:
                priority = current_priority
            if not due_date:
                due_date = current_due_date
            if not monthly_action_id:
                monthly_action_id = current_monthly_action_id
            if not portion:
                portion = current_portion

            # Retrieve assignee_id from assigned_person reference
            if assigned_person:
                cursor.execute(
                    "SELECT id FROM users WHERE username = ?",
                    (assigned_person,)
                )
                assignee_row = cursor.fetchone()
                if not assignee_row:
                    print("Error: Assigned person not found!")
                    return "Error: Assigned person not found!", 400
                assignee_id = assignee_row[0]
            else:
                assignee_id = None

            # Check task assignment hierarchy if assignee_id is provided
            if assignee_id:
                # Get assigner's role
                cursor.execute(
                    "SELECT role FROM users WHERE id = ?",
                    (user_id,)
                )
                assigner_role = cursor.fetchone()[0]
                # Get assignee's role
                cursor.execute(
                    "SELECT role FROM users WHERE id = ?",
                    (assignee_id,)
                )
                assignee_role = cursor.fetchone()[0]
                # Check if assignment is allowed based on hierarchy
                cursor.execute(
                    """
                    SELECT r1.role_level as assigner_level, r2.role_level as assignee_level
                    FROM user_roles r1, user_roles r2
                    WHERE r1.role_name = ? AND r2.role_name = ?
                    """,
                    (assigner_role, assignee_role)
                )
                levels = cursor.fetchone()
                if not levels or levels[0] > levels[1]:
                    print("Error: Invalid task assignment hierarchy")
                    return "Error: Invalid task assignment hierarchy", 403
            if user_id == current_approved_by and status == 'Completed':
               update_approval = "Approved!" 
               percentage_completion = 100
            else:
               update_approval = "Pending"
               due_date = current_due_date
               priority = current_priority
               description = current_description
               portion = current_portion
               monthly_action_id = current_monthly_action_id
               assigned_person = current_assigned_person
            # Update the task without changing the task assigner if the user is an employee
            if user_role == 'Employee':
                cursor.execute("""
                    UPDATE tasks
                    SET assigned_person = ?, description = ?, priority = ?, status = ?, 
                        percentage_completion = ?, updates = ?, due_date = ?, monthly_action_id = ?, 
                        requires_approval = ?, approved_by = ?, approval_status = ?
                    WHERE id = ? AND (user_id = ? OR assigned_by = ? OR approved_by = ? OR assigned_person = (
                        SELECT username FROM users WHERE id = ?
                    ))
                """, (assigned_person, description, priority, status, percentage_completion, update_entry,
                      due_date, monthly_action_id, 1 if assignee_id else 0, current_approved_by, update_approval, task_id, user_id, current_assigned_by, user_id, user_id))
            else:
                cursor.execute("""
                    UPDATE tasks
                    SET assigned_person = ?, description = ?, priority = ?, status = ?, 
                        percentage_completion = ?, updates = ?, due_date = ?, monthly_action_id = ?,  
                        assigned_by = ?, requires_approval = ?, approved_by = ?, approval_status = ?
                    WHERE id = ? AND (user_id = ? OR assigned_by = ? OR approved_by = ? OR assigned_person = (
                        SELECT username FROM users WHERE id = ?
                    ))
                """, (assigned_person, description, priority, status, percentage_completion, update_entry,
                      due_date, monthly_action_id,  user_id, 1 if assignee_id else 0, current_approved_by, update_approval, task_id, user_id, user_id, user_id, user_id))

            conn.commit()
 

        # If the task is completed, update the monthly action plan progress
            if status == 'Completed' and current_status != 'Completed' and monthly_action_id:
                # Calculate total completed portions for this monthly action
                cursor.execute("""
                    SELECT COALESCE(SUM(portion), 0) as completed_portions
                    FROM tasks
                    WHERE monthly_action_id = ? AND status = 'Completed'
                """, (monthly_action_id,))
                completed_portions = cursor.fetchone()[0]

                # Get the monthly action's target portion
                cursor.execute("""
                    SELECT target_portion, semi_annual_plan_id
                    FROM monthly_action_items
                    WHERE id = ?
                """, (monthly_action_id,))
                monthly_action = cursor.fetchone()
                target_portion = monthly_action[0]
                semi_annual_plan_id = monthly_action[1]

                # Update monthly action progress
                percentage = min(round((completed_portions / target_portion) * 100), 100) if target_portion > 0 else 0
                cursor.execute("""
                    UPDATE monthly_action_items
                    SET current_value = ?,
                        percentage_completion = ?,
                        status = CASE 
                            WHEN ? >= target_portion THEN 'Completed'
                            ELSE status 
                        END
                    WHERE id = ?
                """, (completed_portions, percentage, completed_portions, monthly_action_id))

                # If monthly action is completed and linked to a semi-annual plan, update it
                if semi_annual_plan_id and completed_portions >= target_portion:
                    cursor.execute("""
                        SELECT COALESCE(SUM(target_portion), 0) as completed_portions
                        FROM monthly_action_items
                        WHERE semi_annual_plan_id = ? AND status = 'Completed'
                    """, (semi_annual_plan_id,))
                    completed_plan_portions = cursor.fetchone()[0]

                    cursor.execute("""
                        UPDATE semi_annual_plans
                        SET current_value = ?,
                            percentage_completion = ROUND(? * 100.0 / target_value),
                            status = CASE 
                                WHEN ? >= target_value THEN 'Completed'
                                ELSE status 
                            END
                        WHERE id = ?
                    """, (completed_plan_portions, completed_plan_portions, completed_plan_portions, semi_annual_plan_id))

            conn.commit()
            flash('Task updated successfully!', 'success')
            return redirect(url_for('home'))
    except sqlite3.Error as e:
        print(f"Database error: {e}")
        flash(f"Error: {e}", "error")
        return redirect(url_for('home'))

@app.route('/delete_task/<int:task_id>', methods=['POST'])
def delete_task(task_id):
    """Delete a specific task and update related monthly action progress."""
    if 'user_id' not in session:
        flash("You need to be logged in to delete tasks.", "error")
        return redirect(url_for('login'))

    user_id = session['user_id']

    try:
        with get_db_connection() as conn:
            cursor = conn.cursor()

            # Get task details before deletion
            cursor.execute("""
                SELECT monthly_action_id, status, portion
                FROM tasks
                WHERE id = ? AND (assigned_by = ? OR approved_by = ?)
            """, (task_id, user_id, user_id))
            task = cursor.fetchone()

            if not task:
                flash("Error: Task not found or you do not have permission to delete it.", "error")
                return redirect(url_for('home'))

            monthly_action_id, task_status, task_portion = task

            # Delete the task
            cursor.execute("DELETE FROM tasks WHERE id = ?", (task_id,))

            # Update monthly action progress if task was completed
            if monthly_action_id and task_status == 'Completed':
                cursor.execute("""
                    UPDATE monthly_action_items
                    SET current_value = (
                        SELECT COALESCE(SUM(portion), 0)
                        FROM tasks
                        WHERE monthly_action_id = ? AND status = 'Completed'
                    ),
                    percentage_completion = (
                        SELECT ROUND(COALESCE(SUM(portion), 0) * 100.0 / target_portion)
                        FROM tasks
                        WHERE monthly_action_id = ? AND status = 'Completed'
                    )
                    WHERE id = ?
                """, (monthly_action_id, monthly_action_id, monthly_action_id))

            conn.commit()
            flash("Task deleted successfully.", "success")
            return redirect(url_for('home'))

    except sqlite3.Error as e:
        print(f"Database error: {e}")
        flash("Error: Unable to delete task.", "error")
        return redirect(url_for('home'))
 
@app.route('/fetch', methods=['GET'])
def fetch_tasks():
    """Fetch tasks for the logged-in user based on filters."""
    if 'user_id' not in session:
        return jsonify({"success": False, "error": "Unauthorized access."}), 401

    user_id = session['user_id']
    status = request.args.get('status', '').strip()
    keyword = request.args.get('keyword', '').strip()
    start_date = request.args.get('start_date', '').strip()
    end_date = request.args.get('end_date', '').strip()
 
    try:
        with sqlite3.connect(DATABASE) as conn:
            cursor = conn.cursor()

            # Base query
            query = """
                SELECT tasks.id, assigned_person, tasks.description, tasks.status, tasks.notes, tasks.updates, tasks.created_at,
                       monthly_action_items.description AS monthly_action_description
                FROM tasks
                LEFT JOIN monthly_action_items
                ON tasks.monthly_action_id = monthly_action_items.id
                WHERE tasks.user_id = ?
            """
            params = [user_id]

            # Apply status filter
            if status:
                query += " AND tasks.status = ?"
                params.append(status)

            # Apply keyword filter
            if keyword:
                query += " AND (tasks.description LIKE ? OR tasks.assigned_person LIKE ? OR monthly_action_items.description LIKE ?)"
                keyword_pattern = f"%{keyword}%"
                params.extend([keyword_pattern,keyword_pattern, keyword_pattern])

            # Apply date range filter
            if start_date and end_date:
                try:
                    # Validate and add date range to the query
                    start_date_obj = datetime.strptime(start_date, '%Y-%m-%d')
                    end_date_obj = datetime.strptime(end_date, '%Y-%m-%d')

                    if start_date_obj > end_date_obj:
                        return jsonify({"success": False, "error": "Start date must be before or equal to end date"}), 400

                    query += " AND tasks.created_at BETWEEN ? AND ?"
                    params.extend([f"{start_date} 00:00:00", f"{end_date} 23:59:59"])
                except ValueError:
                    return jsonify({"success": False, "error": "Invalid date format. Use YYYY-MM-DD"}), 400

            # Execute the query
            print(f"Executing query: {query} with params: {params}")  # Debugging log
            cursor.execute(query, params)
            tasks = cursor.fetchall()

        # Prepare response
        return jsonify({
            "success": True,
            "tasks": [
                {
                    "id": task[0],
                    "assigned_person": task[1] or "Not Assigned",
                    "description": task[2],
                    "status": task[3],
                    "notes": task[4] or "",
                    "updates": task[5] or "",
                    "created_at": task[6],
                    "monthly_action_description": task[7] or "No linked action"
                }
                for task in tasks
            ]
        })
    except sqlite3.Error as e:
        print(f"Database error: {e}")
        return jsonify({"success": False, "error": "Unable to fetch tasks"}), 500

@app.route('/export', methods=['GET'])
def export_tasks():
    """Export tasks for the logged-in user within a specified date range as a CSV file."""
    if 'user_id' not in session:
        return redirect(url_for('login'))

    user_id = session['user_id']
    start_date = request.args.get('start_date')
    end_date = request.args.get('end_date')

    try:
        with get_db_connection() as conn:
            cursor = conn.cursor()
            # Base query with user-specific filtering
            query = """
                SELECT 
                    id, assigned_person, description, priority, status, 
                    percentage_completion, notes, updates, due_date, created_at,
                    (SELECT description FROM monthly_action_items WHERE id = tasks.monthly_action_id) AS monthly_action
                FROM tasks
                WHERE user_id = ?
            """
            params = [user_id]

            # Apply date range filtering if provided
            if start_date and end_date:
                try:
                    # Ensure dates are in the correct format
                    start_date = f"{start_date} 00:00:00"  # Start at midnight
                    end_date = f"{end_date} 23:59:59"      # End at the last second of the day
                    
                    # Add the date filter to the query
                    query += " AND created_at BETWEEN ? AND ?"
                    params.extend([start_date, end_date])
                except ValueError:
                    return jsonify({"error": "Invalid date format. Use YYYY-MM-DD"}), 400


            cursor.execute(query, params)
            tasks = cursor.fetchall()

        # Prepare CSV content
        output = BytesIO()
        text_io = TextIOWrapper(output, encoding='utf-8', newline='')
        writer = csv.writer(text_io)
        
        # Write header
        writer.writerow([
            "ID", "Assigned Person", "Description", "Priority", "Status",
            "Completion (%)", "Notes", "Updates", "Due Date", "Created At", "Monthly Action"
        ])

        # Write task data
        for task in tasks:
            writer.writerow([
                task[0],  # ID
                task[1] if task[1] else "Not Assigned",  # Assigned Person
                task[2],  # Description
                task[3],  # Priority
                task[4],  # Status
                task[5],  # Completion (%)
                task[6] if task[6] else "",  # Notes
                task[7] if task[7] else "",  # Updates
                task[8] if task[8] else "No Due Date",  # Due Date
                task[9],  # Created At
                task[10] if task[10] else "No linked action"  # Monthly Action
            ])

        # Ensure all data is written to the buffer
        text_io.flush()
        output.seek(0)  # Reset the buffer pointer to the start
        text_io.detach()  # Detach the TextIOWrapper to prevent closing BytesIO

        # Send the file as a response
        return send_file(
            output,
            mimetype='text/csv',
            as_attachment=True,
            download_name='tasks.csv'
        )
    except sqlite3.Error as e:
        print(f"Database error: {e}")
        return "Error: Unable to export tasks.", 500

@app.route('/fetch_monthly_actions', methods=['GET'])
def fetch_actions():
    """Fetch monthly actions for the logged-in user based on filters."""
    if 'user_id' not in session:
        return jsonify({"success": False, "error": "Unauthorized access."}), 401

    user_id = session['user_id']
    status = request.args.get('status', '').strip()
    keyword = request.args.get('keyword', '').strip()
    start_date = request.args.get('start_date', '').strip()
    end_date = request.args.get('end_date', '').strip()

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

            # Apply status filter
            if status:
                query += " AND status = ?"
                params.append(status)

            # Apply keyword filter
            if keyword:
                query += " AND (description LIKE ? OR notes LIKE ?)"
                keyword_pattern = f"%{keyword}%"
                params.extend([keyword_pattern, keyword_pattern])

            # Apply date range filter
            if start_date and end_date:
                try:
                    start_date_obj = datetime.strptime(start_date, '%Y-%m-%d')
                    end_date_obj = datetime.strptime(end_date, '%Y-%m-%d')

                    if start_date_obj > end_date_obj:
                        return jsonify({"success": False, "error": "Start date must be before or equal to end date"}), 400

                    query += " AND created_at BETWEEN ? AND ?"
                    params.extend([f"{start_date} 00:00:00", f"{end_date} 23:59:59"])
                except ValueError:
                    return jsonify({"success": False, "error": "Invalid date format. Use YYYY-MM-DD"}), 400

            # Execute the query
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
                    "created_at": action[4],
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
        flash("Unauthorized access. Please log in.", "error")
        return redirect(url_for('login'))
    
    user_id = session['user_id']
    
    if request.method == 'POST':
        description = request.form.get('description')
        priority = request.form.get('priority', 'Medium')
        due_date = request.form.get('due_date')
        notes = request.form.get('notes', '')
        semi_annual_plan_id = request.form.get('semi_annual_plan_id')
        try:
            target_portion = float(request.form.get('target_portion', 0))
        except ValueError:
            target_portion = 0
        
        if not description:
            flash("Description is required.", "error")
            return redirect(url_for('monthly_action'))

        try:
            with get_db_connection() as conn:
                cursor = conn.cursor()
                
                if semi_annual_plan_id:
                    # Validate target portion against remaining plan target
                    cursor.execute('''
                        SELECT target_value,
                        (SELECT COALESCE(SUM(target_portion), 0)
                         FROM monthly_action_items
                         WHERE semi_annual_plan_id = ?)
                        as allocated_portions
                        FROM semi_annual_plans WHERE id = ?
                    ''', (semi_annual_plan_id, semi_annual_plan_id))
                    
                    plan_data = cursor.fetchone()
                    if plan_data:
                        total_target = plan_data[0] or 0
                        allocated = plan_data[1] or 0
                        remaining = total_target - allocated
                        
                        if target_portion > remaining:
                            flash(f"Error: Target portion ({target_portion}) exceeds remaining plan target ({remaining}).", "error")
                            return redirect(url_for('monthly_action'))

                    cursor.execute('''
                        INSERT INTO monthly_action_items 
                        (user_id, description, priority, due_date, notes, status, 
                         semi_annual_plan_id, target_portion)
                        VALUES (?, ?, ?, ?, ?, 'Open', ?, ?)
                    ''', (user_id, description, priority, due_date, notes, 
                          semi_annual_plan_id, target_portion))

                else:
                    # Insert monthly action item without linking to semi-annual plans
                    cursor.execute('''
                        INSERT INTO monthly_action_items 
                        (user_id, description, priority, due_date, notes, status, target_portion)
                        VALUES (?, ?, ?, ?, ?, 'Open', ?)
                    ''', (user_id, description, priority, due_date, notes, target_portion))
                
                conn.commit()
                flash('Monthly action created successfully!', 'success')
                
        except sqlite3.Error as e:
            flash(f"Error: {str(e)}", "error")
            
        return redirect(url_for('monthly_action'))

    # Fetch active semi-annual plans and monthly actions
    try:
        with get_db_connection() as conn:
            cursor = conn.cursor()
            
            cursor.execute('''
                SELECT sp.id, sp.title, sp.target_value,
                (SELECT COALESCE(SUM(target_portion), 0)
                 FROM monthly_action_items
                 WHERE semi_annual_plan_id = sp.id) as allocated_portions
                FROM semi_annual_plans sp
                WHERE sp.user_id = ? AND sp.status != 'Completed'
            ''', (user_id,))
            semi_annual_plans = cursor.fetchall()
            
            cursor.execute('''
                SELECT ma.*, sp.title as plan_title, sp.target_value,
                (SELECT COALESCE(SUM(portion), 0)
                 FROM tasks
                 WHERE monthly_action_id = ma.id) as allocated_task_portions
                FROM monthly_action_items ma
                LEFT JOIN semi_annual_plans sp ON ma.semi_annual_plan_id = sp.id
                WHERE ma.user_id = ? AND ma.status NOT IN ('Completed', 'Cancelled')
                ORDER BY ma.created_at DESC
            ''', (user_id,))
            monthly_actions = cursor.fetchall()
            
            return render_template('monthly_action.html', 
                                monthly_actions=monthly_actions,
                                semi_annual_plans=semi_annual_plans)
                                
    except sqlite3.Error as e:
        flash(f"Error: Unable to fetch data. Details: {str(e)}", "error")
        return redirect(url_for('monthly_action'))

@app.route('/update_monthly_action/<int:action_id>', methods=['POST'])
def update_monthly_action(action_id):
    """Update a monthly action status and handle target portion updates."""
    if 'user_id' not in session:
        flash("Unauthorized access. Please log in.", "error")
        return redirect(url_for('login'))    
    user_id = session['user_id']    
    
    status = request.form.get('status', 'Open')
    percentage_completion = request.form.get('percentage_completion', '').strip()
    notes = request.form.get('notes', '').strip()
    description = request.form.get('revised_description', '').strip()
    priority = request.form.get('priority', 'Medium')
    due_date = request.form.get('due_date', '').strip()
    target_portion = request.form.get('target_portion', '').strip()
   
    
    try:
        # Handle percentage completion
        if percentage_completion:
            try:
                percentage_completion = int(percentage_completion)
            except ValueError:
                # Handle the case where the conversion fails
                percentage_completion = None
                # You can also add logging or an error message here
        else:
            # Handle the case where the value is empty
            percentage_completion = None

        # Handle target portion
        if target_portion:
            try:
                target_portion = float(target_portion)
            except ValueError:
                target_portion = None
        else:
            target_portion = None

        with get_db_connection() as conn:
            cursor = conn.cursor()
            
            # Fetch the existing action with semi-annual plan details
            cursor.execute("""
                SELECT ma.description, ma.priority, ma.status, ma.due_date, ma.notes, 
                       ma.percentage_completion, ma.semi_annual_plan_id, ma.target_portion,
                       sp.target_value, 
                       (SELECT COALESCE(SUM(target_portion), 0)
                        FROM monthly_action_items
                        WHERE semi_annual_plan_id = ma.semi_annual_plan_id
                        AND id != ma.id) as other_portions
                FROM monthly_action_items ma
                LEFT JOIN semi_annual_plans sp ON ma.semi_annual_plan_id = sp.id
                WHERE ma.id = ? AND ma.user_id = ?
            """, (action_id, user_id))
            
            # Fetch one result from the query
            action = cursor.fetchone()
            if not action:
                flash("Error: Action not found or unauthorized.", "error")
                return redirect(url_for('monthly_action'))

            (current_description, current_priority, current_status, current_due_date, 
             current_notes, current_percentage, semi_annual_plan_id, current_target_portion,
             plan_target_value, other_portions) = action

            # Validate target portion if it's being updated
            if target_portion is not None and semi_annual_plan_id:
                available_target = plan_target_value - other_portions
                if target_portion > available_target:
                    flash(f"Error: Target portion ({target_portion}) exceeds available target ({available_target}).", "error")
                    return redirect(url_for('monthly_action'))

            # Use current values if new ones aren't provided
            description = description or current_description
            status = status if status != "Open" else current_status
            priority = priority or current_priority
            due_date = due_date or current_due_date
            target_portion = target_portion if target_portion is not None else current_target_portion
            percentage_completion = percentage_completion if percentage_completion is not None else current_percentage

            # Create update entry for notes
            update_entry = (
                (current_notes or "") +
                f"\n\n== Update ({datetime.now().strftime('%Y-%m-%d %H:%M')})\n"
                f"{notes or 'No notes'} | Status: {status}"
            )
            if not description: 
                description = current_description
            if  status == "Open" or not status: 
                status = current_status
            if  percentage_completion == 0: 
                percentage_completion = current_percentage    
            if  not priority: 
                priority = current_priority    
            if  not due_date: 
                due_date = current_due_date    
            if target_portion != current_target_portion:
                update_entry += f" | Target Portion: {target_portion}"
            update_entry += "\n"

            # Update the monthly action
            cursor.execute("""
                UPDATE monthly_action_items
                SET description = ?, priority = ?, status = ?, due_date = ?, 
                    notes = ?, percentage_completion = ?, target_portion = ?
                WHERE id = ? AND user_id = ?
            """, (description, priority, status, due_date, update_entry, 
                  percentage_completion, target_portion, action_id, user_id))

            # If status changed to 'Completed', update semi-annual plan progress
            if status == 'Completed' and current_status != 'Completed' and semi_annual_plan_id:
                cursor.execute("""
                    UPDATE semi_annual_plans
                    SET current_value = (
                        SELECT COALESCE(SUM(target_portion), 0)
                        FROM monthly_action_items
                        WHERE semi_annual_plan_id = ? AND status = 'Completed'
                    ),
                    percentage_completion = (
                        SELECT ROUND(COALESCE(SUM(target_portion), 0) * 100.0 / target_value)
                        FROM monthly_action_items
                        WHERE semi_annual_plan_id = ? AND status = 'Completed'
                    )
                    WHERE id = ?
                """, (semi_annual_plan_id, semi_annual_plan_id, semi_annual_plan_id))

                # Check if plan should be auto-completed
                cursor.execute("""
                    UPDATE semi_annual_plans
                    SET status = 'Completed'
                    WHERE id = ?
                    AND current_value >= target_value
                    AND status != 'Completed'
                """, (semi_annual_plan_id,))

            conn.commit()

        flash("Monthly action updated successfully.", "success")
        return redirect(url_for('monthly_action'))
    except sqlite3.Error as e:
        flash(f"Error: Unable to update monthly action item. Details: {str(e)}", "error")
        return redirect(url_for('monthly_action'))

@app.route('/delete_monthly_action/<int:action_id>', methods=['POST'])
def delete_monthly_action(action_id):
    """Delete a monthly action item along with its related tasks."""
    if 'user_id' not in session:
        flash("Unauthorized access. Please log in.", "error")
        return redirect(url_for('login'))

    user_id = session['user_id']
    
    try:
        with sqlite3.connect(DATABASE) as conn:
            cursor = conn.cursor()
            
            # First, remove any linked tasks
            cursor.execute("DELETE FROM tasks WHERE monthly_action_id = ?", (action_id,))
            
            # Then delete the monthly action item
            cursor.execute("DELETE FROM monthly_action_items WHERE id = ? AND user_id = ?", (action_id, user_id))
            conn.commit()
            
        flash("Monthly action and related tasks deleted successfully.", "success")
        return redirect(url_for('monthly_action'))
    except sqlite3.Error as e:
        flash(f"Error: Unable to delete monthly action item. Details: {str(e)}", "error")
        return redirect(url_for('monthly_action'))

# Add new route handlers
@app.route('/semi-annual-plans', methods=['GET', 'POST'])
def semi_annual_plans():
    if 'user_id' not in session:
        return redirect(url_for('login'))
    
    user_id = session['user_id']
    
    if request.method == 'POST':
        title = request.form.get('title')
        description = request.form.get('description')
        target_value = request.form.get('target_value')
        start_date = request.form.get('start_date')
        end_date = request.form.get('end_date')
        priority = request.form.get('priority', 'Medium')
        notes = request.form.get('notes', '')
        
        try:
            with get_db_connection() as conn:
                cursor = conn.cursor()
                cursor.execute('''
                    INSERT INTO semi_annual_plans 
                    (user_id, title, description, target_value, start_date, end_date, priority, notes)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                ''', (user_id, title, description, target_value, start_date, end_date, priority, notes))
                conn.commit()
                flash('Semi-annual plan created successfully!', 'success')
        except sqlite3.Error as e:
            flash(f'Error creating plan: {str(e)}', 'error')
        
        return redirect(url_for('semi_annual_plans'))
    
    # Fetch existing plans
    try:
        with get_db_connection() as conn:
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()
            cursor.execute('''
                SELECT id, title, description, target_value, current_value, 
                       start_date, end_date, priority, status, notes, percentage_completion
                FROM semi_annual_plans
                WHERE user_id = ? AND status != 'Completed'
                ORDER BY created_at DESC
            ''', (user_id,))
            plans = cursor.fetchall()
            
            # Convert plans to list of dictionaries and add action stats
            plans_with_stats = []
            for plan in plans:
                # Convert Row object to dictionary
                plan_dict = dict(plan)
                
                cursor.execute('''
                    SELECT COUNT(*) as total_actions,
                           SUM(CASE WHEN status = 'Completed' THEN 1 ELSE 0 END) as completed_actions
                    FROM monthly_action_items
                    WHERE semi_annual_plan_id = ?
                ''', (plan_dict['id'],))
                stats = cursor.fetchone()
                plan_dict['action_stats'] = dict(stats)
                plans_with_stats.append(plan_dict)
    
    except sqlite3.Error as e:
        flash(f'Error fetching plans: {str(e)}', 'error')
        plans_with_stats = []
    
    return render_template('semi_annual_plans.html', plans=plans_with_stats)

@app.route('/update_semi_annual_plan/<int:plan_id>', methods=['POST'])
def update_semi_annual_plan(plan_id):
    if 'user_id' not in session:
        flash("Unauthorized access. Please log in.", "error")
        return redirect(url_for('login'))

    user_id = session['user_id']
    title = request.form.get('title')
    description = request.form.get('description')
    target_value = request.form.get('target_value')
    start_date = request.form.get('start_date')
    end_date = request.form.get('end_date')
    priority = request.form.get('priority')
    status = request.form.get('status')
    current_value = request.form.get('current_value')
    notes = request.form.get('notes')
    percentage_completion = request.form.get('percentage_completion')

    try:
        with get_db_connection() as conn:
            cursor = conn.cursor()

            # Fetch the existing semi-annual plan details
            cursor.execute("""
                SELECT title, description, target_value, start_date, end_date, priority, notes
                FROM semi_annual_plans
                WHERE id = ? AND user_id = ?
            """, (plan_id, user_id))

            plan = cursor.fetchone()
            if not plan:
                flash("Error: Plan not found or unauthorized.", "error")
                return redirect(url_for('semi_annual_plans'))

            (current_title, current_description, current_target_value, 
             current_start_date, current_end_date, current_priority, current_notes) = plan

            # Use provided values or existing ones if new ones aren't provided
            title = title if title else current_title
            description = description if description else current_description
            target_value = target_value if target_value else current_target_value
            start_date = start_date if start_date else current_start_date
            end_date = end_date if end_date else current_end_date
            priority = priority if priority else current_priority
            notes = notes if notes else current_notes

            # Ensure values are properly converted to appropriate types
            target_value = float(target_value) if target_value is not None else current_target_value

            # Update the semi-annual plan
            cursor.execute("""
                UPDATE semi_annual_plans
                SET title = ?, description = ?, target_value = ?, start_date = ?, end_date = ?, 
                    priority = ?,status = ?, current_value = ?, notes = ?, percentage_completion = ?
                WHERE id = ? AND user_id = ?
            """, (title, description, target_value, start_date, end_date, priority,status, current_value, notes, percentage_completion, plan_id, user_id))

            conn.commit()
            flash('Plan updated successfully!', 'success')
    except sqlite3.Error as e:
        flash(f'Error updating plan: {str(e)}', 'error')

    return redirect(url_for('semi_annual_plans'))
 
@app.route('/fetch_historical_semi_annual_plans', methods=['GET'])
def fetch_historical_semi_annual_plans():
    """Fetch historical semi-annual plans for the logged-in user based on filters."""
    if 'user_id' not in session:
        return jsonify({"success": False, "error": "Unauthorized access."}), 401

    user_id = session['user_id']
    status = request.args.get('status', '').strip()
    keyword = request.args.get('keyword', '').strip()
    start_date = request.args.get('start_date', '').strip()
    end_date = request.args.get('end_date', '').strip()

    try:
        with get_db_connection() as conn:
            cursor = conn.cursor()
            query = """
                SELECT id, title, description, target_value, start_date, end_date, priority, status, notes, created_at 
                FROM semi_annual_plans 
                WHERE user_id = ?
            """
            params = [user_id]

            # Apply status filter
            if status:
                query += " AND status = ?"
                params.append(status)

            # Apply keyword filter
            if keyword:
                query += " AND (title LIKE ? OR description LIKE ?)"
                keyword_pattern = f"%{keyword}%"
                params.extend([keyword_pattern, keyword_pattern])

            # Apply date range filter
            if start_date and end_date:
                try:
                    start_date_obj = datetime.strptime(start_date, '%Y-%m-%d')
                    end_date_obj = datetime.strptime(end_date, '%Y-%m-%d')

                    if start_date_obj > end_date_obj:
                        return jsonify({"success": False, "error": "Start date must be before or equal to end date"}), 400

                    query += " AND created_at BETWEEN ? AND ?"
                    params.extend([f"{start_date} 00:00:00", f"{end_date} 23:59:59"])
                except ValueError:
                    return jsonify({"success": False, "error": "Invalid date format. Use YYYY-MM-DD"}), 400

            # Execute the query
            cursor.execute(query, params)
            semi_annual_plans = cursor.fetchall()

        return jsonify({
            "success": True,
            "semi_annual_plans": [
                {
                    "id": plan[0],
                    "title": plan[1],
                    "description": plan[2],
                    "target_value": plan[3],
                    "start_date": plan[4],
                    "end_date": plan[5],
                    "priority": plan[6],
                    "status": plan[7],
                    "notes": plan[8],
                    "created_at": plan[9],
                }
                for plan in semi_annual_plans
            ]
        })
    except sqlite3.Error as e:
        print(f"Database error: {e}")
        return jsonify({"success": False, "error": "Unable to fetch semi-annual plans"}), 500 
@app.route('/delete_semi_annual_plan/<int:plan_id>', methods=['POST'])
def delete_semi_annual_plan(plan_id):
    """Delete a semi-annual plan along with its related monthly action items."""
    if 'user_id' not in session:
        flash("Unauthorized access. Please log in.", "error")
        return redirect(url_for('login'))

    user_id = session['user_id']
    
    try:
        with get_db_connection() as conn:
            cursor = conn.cursor()
            
            # First, delete related monthly actions
            cursor.execute("DELETE FROM monthly_action_items WHERE semi_annual_plan_id = ?", (plan_id,))
            
            # Then delete the semi-annual plan
            cursor.execute("DELETE FROM semi_annual_plans WHERE id = ? AND user_id = ?", (plan_id, user_id))
            conn.commit()
            
        flash("Semi-annual plan and related monthly actions deleted successfully.", "success")
        return redirect(url_for('semi_annual_plans'))
    except sqlite3.Error as e:
        flash(f"Error: Unable to delete semi-annual plan. Details: {str(e)}", "error")
        return redirect(url_for('semi_annual_plans'))
     
@app.route('/upload_semi_annual_plans', methods=['POST'])
def upload_semi_annual_plans():
    """Upload and process semi-annual plans for the logged-in user."""
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
        required_columns = {'title', 'description', 'target_value', 'start_date', 'end_date', 'priority', 'notes'}
        if not required_columns.issubset(df.columns):
            return f"Error: Missing required columns. Required columns are {', '.join(required_columns)}.", 400
        
        # Clean and validate data
        invalid_rows = []
        for index, row in df.iterrows():
            # Validate required fields
            if pd.isna(row['title']) or pd.isna(row['description']) or pd.isna(row['target_value']) or pd.isna(row['start_date']) or pd.isna(row['end_date']):
                invalid_rows.append(index + 1)
                continue

            # Validate date
            try:
                row['start_date'] = pd.to_datetime(row['start_date']).date() if not pd.isna(row['start_date']) else None
                row['end_date'] = pd.to_datetime(row['end_date']).date() if not pd.isna(row['end_date']) else None
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
                    INSERT INTO semi_annual_plans 
                    (user_id, title, description, target_value, start_date, end_date, priority, notes)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                ''', (user_id, row['title'], row['description'], row['target_value'], row['start_date'], row['end_date'], row['priority'].capitalize(), row['notes']))
                conn.commit()

        # Return success and invalid row information
        if invalid_rows:
            return f"Upload completed with errors. Invalid rows: {invalid_rows}", 200
        
        return redirect(url_for('semi_annual_plans'))
    except Exception as e:
        print(f"Error processing file: {e}")
        return f"Error: Unable to process the uploaded file. Details: {str(e)}", 500
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
            
            # Base queries with user filter
            task_base_query = "FROM tasks WHERE user_id = ?"
            action_base_query = "FROM monthly_action_items WHERE user_id = ?"
            params = [user_id]

            # Date range filtering
            if start_date and end_date:
                # Validate date range format
                try:
                    # Validate and format the date range
                    start_date = f"{start_date} 00:00:00"  # Include time for the start of the day
                    end_date = f"{end_date} 23:59:59"    # Include time for the end of the day

                    if start_date > end_date:
                        return jsonify({"error": "Invalid date range: Start date must be before or equal to end date"}), 400

                    # Add the date range filter to the queries using 'created_at'
                    task_base_query += " AND (created_at BETWEEN ? AND ?)"
                    action_base_query += " AND (created_at BETWEEN ? AND ?)"
                    params.extend([start_date, end_date])
                except ValueError:
                    return jsonify({"error": "Invalid date format. Please use YYYY-MM-DD format."}), 400

            # 1. Priority vs Completion Percentage
            # Concatenating description and priority (optional)
            cursor.execute(f"""
                SELECT description || ' ' || priority AS description_and_priority, 
                       AVG(percentage_completion) AS avg_completion 
                {action_base_query}
                GROUP BY description_and_priority
            """, params)
            
            priority_completion_data = cursor.fetchall()


            # 2. Monthly Progress for Tasks
            cursor.execute(f"""
                SELECT strftime('%Y-%m', created_at) AS month,
                       SUM(CASE WHEN status = 'Completed' THEN 1 ELSE 0 END) AS completed,
                       SUM(CASE WHEN status = 'In Progress' THEN 1 ELSE 0 END) AS in_progress,
                       SUM(CASE WHEN status = 'Open' THEN 1 ELSE 0 END) AS open
                {action_base_query}
                GROUP BY month
                ORDER BY month
            """, params)
            monthly_task_progress = cursor.fetchall()
            
            # 3. Monthly Progress for Action Items
            cursor.execute(f"""
                SELECT strftime('%Y-%m', created_at) AS month,
                       SUM(CASE WHEN status = 'Completed' THEN 1 ELSE 0 END) AS completed,
                       SUM(CASE WHEN status = 'In Progress' THEN 1 ELSE 0 END) AS in_progress,
                       SUM(CASE WHEN status = 'Open' THEN 1 ELSE 0 END) AS open
                {action_base_query}
                GROUP BY month
                ORDER BY month
            """, params)
            monthly_action_progress = cursor.fetchall()
            
            # 4. Action Item Status Breakdown
            cursor.execute(f"""
                SELECT status, COUNT(*) AS count
                {action_base_query}
                GROUP BY status
            """, params)
            action_status_data = cursor.fetchall()
            status_breakdown = {row[0]: row[1] for row in action_status_data}

            # 5. Total Tasks by Priority
            cursor.execute(f"""
                SELECT priority, COUNT(*) AS total_tasks
                {action_base_query}
                GROUP BY priority
            """, params)
            total_tasks_by_priority = dict(cursor.fetchall())

            # 6. Task Completion Timeline
            cursor.execute(f"""
                SELECT strftime('%Y-%m-%d', created_at) AS date,
                       COUNT(CASE WHEN status = 'Completed' THEN 1 END) AS completed_tasks
                {action_base_query}
                GROUP BY date
                ORDER BY date
            """, params)
            task_completion_timeline = cursor.fetchall()
            
            # 7. Action Items Completion Status by Priority
            cursor.execute(f"""
                SELECT priority,
                       AVG(percentage_completion) AS completion_percentage
                {action_base_query}
                GROUP BY priority
            """, params)
            completion_status_data = cursor.fetchall()

            # Prepare JSON response
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
                },
                "completion_status_by_priority": {row[0]: row[1] for row in completion_status_data}
            })
    except sqlite3.Error as e:
        print(f"Database error: {e}")
        return jsonify({"error": "Failed to fetch progress data."}), 500  
@app.route('/upload_tasks', methods=['POST'])
def upload_tasks():
    """Upload and process tasks from Excel/CSV file for the logged-in user."""
    if 'user_id' not in session:
        flash("Error: Please login first.", "error")
        return redirect(url_for('login'))

    user_id = session['user_id']
    file = request.files.get('file')
    if not file:
        flash("Error: No file uploaded.", "error")
        return redirect(url_for('home'))
    
    try:
        # Determine file type and read into DataFrame
        if file.filename.endswith('.csv'):
            df = pd.read_csv(file)
        elif file.filename.endswith(('.xls', '.xlsx')):
            df = pd.read_excel(file)
        else:
            flash("Error: Invalid file format. Please upload an Excel or CSV file.", "error")
            return redirect(url_for('home'))
        
        # Normalize column names (case insensitive)
        df.columns = [col.strip().lower() for col in df.columns]
        
        # Validate required column (only description is mandatory)
        if 'description' not in df.columns:
            flash("Error: Missing required column 'description'.", "error")
            return redirect(url_for('home'))
        
        # Connect to database
        conn = get_db_connection()
        cursor = conn.cursor()
        
        success_count = 0
        error_rows = []
        
        # Start a transaction
        conn.execute("BEGIN")
        
        try:
            # Process each row in the DataFrame
            for index, row in df.iterrows():
                try:
                    # Only description is mandatory
                    if pd.isna(row['description']) or str(row['description']).strip() == '':
                        error_rows.append(index + 1)
                        continue

                    # Priority handling (optional)
                    priority = 'Medium'  # Default priority
                    if 'priority' in df.columns and not pd.isna(row['priority']):
                        priority_val = str(row['priority']).strip().lower()
                        if priority_val in ['high', 'h']:
                            priority = 'High'
                        elif priority_val in ['medium', 'm', 'med']:
                            priority = 'Medium'
                        elif priority_val in ['low', 'l']:
                            priority = 'Low'

                    # Due date handling (optional)
                    due_date = None
                    if 'due_date' in df.columns and not pd.isna(row['due_date']):
                        try:
                            date_formats = [
                                '%Y-%m-%d', '%d-%m-%Y', '%m-%d-%Y',
                                '%Y/%m/%d', '%d/%m/%Y', '%m/%d/%Y',
                                '%d.%m.%Y', '%m.%d.%Y', '%Y.%m.%d',
                                '%b %d %Y', '%B %d %Y',
                                '%d %b %Y', '%d %B %Y'
                            ]
                            
                            date_str = str(row['due_date']).strip()
                            for fmt in date_formats:
                                try:
                                    due_date = pd.to_datetime(date_str, format=fmt).strftime('%Y-%m-%d')
                                    break
                                except:
                                    continue
                            
                            if due_date is None:
                                due_date = pd.to_datetime(date_str).strftime('%Y-%m-%d')
                        except:
                            due_date = None

                    # Assigned person handling (optional)
                    assigned_person = None
                    assignee_id = None
                    if 'assigned_person' in df.columns and not pd.isna(row['assigned_person']):
                        assigned_person = str(row['assigned_person']).strip()
                        cursor.execute("""
                            SELECT id FROM users 
                            WHERE LOWER(username) = LOWER(?)
                        """, (assigned_person,))
                        assignee_row = cursor.fetchone()
                        if assignee_row:
                            assignee_id = assignee_row[0]

                    # Insert task into database
                    cursor.execute("""
                        INSERT INTO tasks (
                            user_id, assigned_person, description, priority, due_date, 
                            status, monthly_action_id, assigned_by, requires_approval, approved_by
                        ) VALUES (?, ?, ?, ?, ?, 'Open', ?, ?, ?, ?)
                    """, (
                        assignee_id if assignee_id else user_id,
                        assigned_person,
                        str(row['description']).strip(),
                        priority,
                        due_date,
                        row.get('monthly_action_id', None) if 'monthly_action_id' in df.columns else None,
                        user_id,
                        1 if assignee_id else 0,
                        user_id
                    ))
                    success_count += 1
                    
                except Exception as e:
                    error_rows.append(index + 1)
                    continue
            
            # Commit the transaction if all went well
            conn.commit()
            
            if success_count > 0:
                flash(f"Success: {success_count} tasks uploaded successfully.", "success")
            
            if error_rows:
                flash(f"Error: Failed to process rows: {', '.join(map(str, error_rows))}.", "error")
            
        except Exception as e:
            conn.rollback()
            flash("Error: Database error occurred.", "error")
        
        finally:
            conn.close()
        
        return redirect(url_for('home'))
        
    except Exception as e:
        flash("Error: Failed to process file.", "error")
        return redirect(url_for('home'))

@app.route('/upload_monthly_actions', methods=['POST'])
def upload_monthly_actions():
    """Upload and process monthly action items for the logged-in user."""
    if 'user_id' not in session:
        flash("Error: Please login first.", "error")
        return redirect(url_for('login'))

    user_id = session['user_id']
    file = request.files.get('file')
    if not file:
        flash("Error: No file uploaded.", "error")
        return redirect(url_for('monthly_action'))
    
    try:
        # Determine file type and read into DataFrame
        if file.filename.endswith('.csv'):
            df = pd.read_csv(file)
        elif file.filename.endswith(('.xls', '.xlsx')):
            df = pd.read_excel(file)
        else:
            flash("Error: Invalid file format. Please upload an Excel or CSV file.", "error")
            return redirect(url_for('monthly_action'))
        
        # Normalize column names (case insensitive)
        df.columns = [col.strip().lower() for col in df.columns]
        
        # Validate required column (only description is mandatory)
        if 'description' not in df.columns:
            flash("Error: Missing required column 'description'.", "error")
            return redirect(url_for('monthly_action'))
        
        # Connect to database
        conn = get_db_connection()
        cursor = conn.cursor()
        
        success_count = 0
        error_rows = []
        
        # Start a transaction
        conn.execute("BEGIN")
        
        try:
            # Process each row in the DataFrame
            for index, row in df.iterrows():
                try:
                    # Only description is mandatory
                    if pd.isna(row['description']) or str(row['description']).strip() == '':
                        error_rows.append(index + 1)
                        continue

                    # Priority handling (optional)
                    priority = 'Medium'  # Default priority
                    if 'priority' in df.columns and not pd.isna(row['priority']):
                        priority_val = str(row['priority']).strip().lower()
                        if priority_val in ['high', 'h']:
                            priority = 'High'
                        elif priority_val in ['medium', 'm', 'med']:
                            priority = 'Medium'
                        elif priority_val in ['low', 'l']:
                            priority = 'Low'

                    # Due date handling (optional)
                    due_date = None
                    if 'due_date' in df.columns and not pd.isna(row['due_date']):
                        try:
                            date_formats = [
                                '%Y-%m-%d', '%d-%m-%Y', '%m-%d-%Y',
                                '%Y/%m/%d', '%d/%m/%Y', '%m/%d/%Y',
                                '%d.%m.%Y', '%m.%d.%Y', '%Y.%m.%d',
                                '%b %d %Y', '%B %d %Y',
                                '%d %b %Y', '%d %B %Y'
                            ]
                            
                            date_str = str(row['due_date']).strip()
                            for fmt in date_formats:
                                try:
                                    due_date = pd.to_datetime(date_str, format=fmt).strftime('%Y-%m-%d')
                                    break
                                except:
                                    continue
                            
                            if due_date is None:
                                due_date = pd.to_datetime(date_str).strftime('%Y-%m-%d')
                        except:
                            due_date = None

                    # Notes handling (optional)
                    notes = str(row['notes']).strip() if 'notes' in df.columns and not pd.isna(row['notes']) else None

                    # Insert monthly action into database
                    cursor.execute("""
                        INSERT INTO monthly_action_items 
                        (user_id, description, priority, status, due_date, notes, percentage_completion)
                        VALUES (?, ?, ?, 'Open', ?, ?, 0)
                    """, (
                        user_id,
                        str(row['description']).strip(),
                        priority,
                        due_date,
                        notes
                    ))
                    success_count += 1
                    
                except Exception as e:
                    error_rows.append(index + 1)
                    continue
            
            # Commit the transaction if all went well
            conn.commit()
            
            if success_count > 0:
                flash(f"Success: {success_count} monthly actions uploaded successfully.", "success")
            
            if error_rows:
                flash(f"Error: Failed to process rows: {', '.join(map(str, error_rows))}.", "error")
            
        except Exception as e:
            conn.rollback()
            flash("Error: Database error occurred.", "error")
        
        finally:
            conn.close()
        
        return redirect(url_for('monthly_action'))
        
    except Exception as e:
        flash("Error: Failed to process file.", "error")
        return redirect(url_for('monthly_action'))
 
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
        # Validate date range if both dates are provided
        if start_date and end_date:
            try:
                start = datetime.strptime(start_date, '%Y-%m-%d').date()
                end = datetime.strptime(end_date, '%Y-%m-%d').date()
                
                # Ensure start date is not after end date
                if start > end:
                    return jsonify({"error": "Invalid date range: Start date must be before or equal to end date"}), 400
            except ValueError:
                return jsonify({"error": "Invalid date format. Use YYYY-MM-DD"}), 400

        with sqlite3.connect(DATABASE) as conn:
            cursor = conn.cursor()

            # Base query
            query = '''
            SELECT
                id,
                description AS name,
                priority,
                percentage_completion AS progress,
                created_at,
                due_date,   -- Include due_date in the query
                status
            FROM tasks
            WHERE user_id = ? AND status IN ('Open', 'In Progress', 'Completed')
            '''
            params = [user_id]

            if start_date and end_date:
                try:
                    # Ensure dates are in the correct format
                    start_date = f"{start_date} 00:00:00"  # Start at midnight
                    end_date = f"{end_date} 23:59:59"      # End at the last second of the day
                    
                    # Add the date filter to the query
                    query += " AND created_at BETWEEN ? AND ?"
                    params.extend([start_date, end_date])
                except ValueError:
                    return jsonify({"error": "Invalid date format. Use YYYY-MM-DD"}), 400


            # Order tasks by priority and progress
            query += ' ORDER BY priority, percentage_completion DESC'

            cursor.execute(query, params)
            tasks = cursor.fetchall()

            # Structure the data as JSON
            task_data = {
                "tasks": [
                    {
                        "id": task[0],
                        "name": task[1] or "Unnamed Task",
                        "priority": task[2] or "Medium",
                        "progress": task[3] or 0,
                        "created_at": task[4] or "No creation date",
                        "due_date": task[5] or None,  # Include due_date or None if not set
                        "status": task[6]
                    }
                    for task in tasks
                ],
                "summary": {
                    "total_tasks": len(tasks),
                    "priorities": {
                        "High": sum(1 for task in tasks if task[2] == "High"),
                        "Medium": sum(1 for task in tasks if task[2] == "Medium"),
                        "Low": sum(1 for task in tasks if task[2] == "Low")
                    },
                    "avg_progress": round(sum(task[3] or 0 for task in tasks) / len(tasks), 2) if tasks else 0
                }
            }

            return jsonify(task_data)

    except sqlite3.Error as e:
        print(f"Database error: {e}")
        return jsonify({"error": "Failed to fetch task data.", "details": str(e)}), 500
    except Exception as e:
        print(f"Unexpected error: {e}")
        return jsonify({"error": "An unexpected error occurred.", "details": str(e)}), 500

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
    """
    Send an email notification for a specific task.
    """
    try:
        # Retrieve and validate inputs
        task_id = request.form.get('task_id')
        recipients = request.form.get('recipients', '[]')
        intent = request.form.get('intent')
        email_subject = request.form.get('subject')
        email_body = request.form.get('body')
        
        # Ensure email body is not None
        email_body = email_body if email_body else ""

        # Validate required inputs

        
        # Parse recipients from JSON string
        recipients = json.loads(recipients)

        # Fetch task details from the database
        with sqlite3.connect(DATABASE) as conn:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT description, priority, status, assigned_person, 
                       due_date, percentage_completion 
                FROM tasks 
                WHERE id = ?
            """, (task_id,))
            task = cursor.fetchone()

        if not task:
            return jsonify({"success": False, "message": "Task not found"}), 404

        task_details = {
            "email_subject": email_subject,
            "email_body": email_body,
            "description": task[0],
            "priority": task[1],
            "status": task[2],
            "assigned_person": task[3],
            "due_date": task[4],
            "percentage_completion": task[5]
        }

        # Send email notifications
        result = email_notifier.send_task_notification(recipients, task_details, intent)

        return jsonify({
            "success": result,
            "message": "Emails sent successfully" if result else "Failed to send emails"
        })

    except sqlite3.Error as db_error:
        print(f"Database error in /send-task-email: {db_error}")
        return jsonify({"success": False, "message": "Database error occurred."}), 500

    except Exception as e:
        print(f"Unexpected error in /send-task-email: {e}")
        return jsonify({"success": False, "message": str(e)}), 500

@app.route('/get-emails', methods=['GET'])
def get_emails():
    """
    Retrieve the list of users for email selection.
    """
    try:
        with open('email_config.json', 'r') as f:
            email_data = json.load(f)

        users = email_data.get('users', [])
        if not users:
            return jsonify({"success": False, "message": "No users found in the email configuration."}), 404

        return jsonify({"success": True, "users": users})

    except FileNotFoundError:
        return jsonify({
            "success": False,
            "message": "Email configuration file not found."
        }), 404

    except json.JSONDecodeError as json_error:
        print(f"JSON error in /get-emails: {json_error}")
        return jsonify({
            "success": False,
            "message": "Error decoding email configuration file."
        }), 500

    except Exception as e:
        print(f"Unexpected error in /get-emails: {e}")
        return jsonify({
            "success": False,
            "message": "An unexpected error occurred.",
            "details": str(e)
        }), 500

@app.route('/search-emails', methods=['GET'])
def search_emails():
    """
    Search for email users based on a keyword from the database.
    """
    keyword = request.args.get('keyword', '').strip().lower()  # Retrieve and sanitize keyword

    if not keyword:
        return jsonify({
            "success": False,
            "message": "Keyword is required for searching."
        }), 400

    try:
        with get_db_connection() as conn:
            cursor = conn.cursor()

            # Search for users in the database by matching the keyword with username or email
            cursor.execute('''
                SELECT username AS name, email
                FROM users
                WHERE LOWER(username) LIKE ? OR LOWER(email) LIKE ?
            ''', (f'%{keyword}%', f'%{keyword}%'))

            users = cursor.fetchall()

            # Convert sqlite3.Row objects to dictionaries
            users = [dict(user) for user in users]

            if not users:
                return jsonify({"success": False, "message": "No users found matching the keyword."}), 404

            return jsonify({
                "success": True,
                "users": users
            })

    except sqlite3.Error as e:
        print(f"Database error in /search-emails: {e}")
        return jsonify({
            "success": False,
            "message": "An unexpected database error occurred.",
            "details": str(e)
        }), 500

    except Exception as e:
        print(f"Unexpected error in /search-emails: {e}")
        return jsonify({
            "success": False,
            "message": "An unexpected error occurred.",
            "details": str(e)
        }), 500

@app.route('/email-management')
def email_management():
    """Render the email management page."""
    return render_template('email_management.html')

@app.route('/signup', methods=['GET', 'POST'])
def signup():
    if request.method == 'POST':
        username = request.form.get('username')
        email = request.form.get('email')
        password = request.form.get('password')
        role = request.form.get('role')
        department = request.form.get('department')
    
        # Validate required fields
        if not all([username, email, password, role, department]):
            result = email_manager.add_user(username, email)
            return jsonify(success=False, message='All required fields must be filled')
        
        # Validate email format
        if not re.match(r"[^@]+@[^@]+\.[^@]+", email):
            return jsonify(success=False, message='Invalid email format')

        # Validate password strength
        if not re.match(r"^(?=.*[A-Za-z])(?=.*\d)[A-Za-z\d]{8,}$", password):
            return jsonify(success=False, 
                           message='Password must be at least 8 characters long and include both letters and numbers')

        # Hash password
        password_hash = bcrypt.hashpw(password.encode('utf-8'), bcrypt.gensalt())

        try:
            with get_db_connection() as conn:
                cursor = conn.cursor()
                
                # Check if username or email already exists
                cursor.execute('SELECT id FROM users WHERE username = ? OR email = ?', (username, email))
                if cursor.fetchone():
                    return jsonify(success=False, message='Username or email already exists')

                # Verify role exists in user_roles table
                cursor.execute('SELECT role_name FROM user_roles WHERE role_name = ?', (role,))
                if not cursor.fetchone():
                    return jsonify(success=False, message='Invalid role selected')

                # Insert new user with role and department
                cursor.execute('''
                    INSERT INTO users (username, email, password_hash, role, department)
                    VALUES (?, ?, ?, ?, ?)
                ''', (username, email, password_hash, role, department))
                
                conn.commit()
                
                return jsonify(success=True, 
                               message=f'Account created successfully as {role}',
                               redirect=url_for('login'))

        except sqlite3.Error as e:
            print(f"Database error: {e}")
            return jsonify(success=False, message='An error occurred while creating your account')

    # GET method - return available roles for the signup form
    try:
        with get_db_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('SELECT role_name FROM user_roles ORDER BY role_level')
            roles = [row[0] for row in cursor.fetchall()]
            return render_template('signup.html', roles=roles)
    except sqlite3.Error as e:
        print(f"Database error: {e}")
        return render_template('signup.html', roles=['Employee'])  # Fallback to basic role

@app.route('/reset-password', methods=['GET', 'POST'])
def reset_password():
    """
    Handle password reset requests.
    Sends an email with a reset link if the user exists.
    """
    if request.method == 'POST':
        email = request.form.get('email')
        
        if not email:
            return jsonify(success=False, message="Email address is required."), 400

        token = secrets.token_urlsafe(16)  # Generate a secure token
        expires_at = datetime.now() + timedelta(hours=1)  # Set token expiration time

        try:
            with get_db_connection() as conn:
                cursor = conn.cursor()
                # Check if the user exists
                cursor.execute('SELECT id FROM users WHERE email = ?', (email,))
                user = cursor.fetchone()

                if user:
                    # Insert the reset token into the database
                    cursor.execute(
                        '''INSERT INTO password_reset_tokens (user_id, token, expires_at) VALUES (?, ?, ?)''',
                        (user['id'], token, expires_at)
                    )
                    conn.commit()

                    # Generate the reset link
                    reset_link = url_for('reset_password_confirm', token=token, _external=True)

                    # Send the password reset email
                    body = f"Click the following link to reset your password: {reset_link}"
                    email_notifier.send_password_reset_email(email, "Password Reset", body)
                    
                    print(f"Password reset link: {reset_link}")  # For debugging purposes
                    return jsonify(success=True, message="Password reset link has been sent to your email.")

                else:
                    return jsonify(success=False, message="Email not found."), 404

        except sqlite3.Error as db_error:
            print(f"Database error: {db_error}")
            return jsonify(success=False, message="An internal error occurred. Please try again later."), 500

        except Exception as e:
            print(f"Unexpected error: {e}")
            return jsonify(success=False, message="An unexpected error occurred. Please try again later."), 500

    # Render the password reset form for GET requests
    return render_template('reset_password.html')

@app.route('/reset-password/<token>', methods=['GET', 'POST'])
def reset_password_confirm(token):
    """
    Handle password reset via a unique token.
    """
    if request.method == 'GET':
        try:
            # Validate the token
            with get_db_connection() as conn:
                cursor = conn.cursor()
                cursor.execute(
                    '''SELECT * FROM password_reset_tokens WHERE token = ? AND expires_at > ? AND used = 0''',
                    (token, datetime.now())
                )
                token_record = cursor.fetchone()

                if token_record:
                    # Render the password reset form
                    return render_template('reset_password_confirm.html', token=token)
                else:
                    return "Invalid or expired token.", 400

        except sqlite3.Error as e:
            print(f"Database error: {e}")
            return "An internal error occurred. Please try again later.", 500

    elif request.method == 'POST':
        # Process the new password submission
        new_password = request.form.get('new_password')
        confirm_password = request.form.get('confirm_new_password')

        # Validate the new password
        if not new_password or not confirm_password:
            return jsonify(success=False, message="Password fields cannot be empty."), 400

        if new_password != confirm_password:
            return jsonify(success=False, message="Passwords do not match."), 400

        if len(new_password) < 8 or not re.search(r'[A-Za-z]', new_password) or not re.search(r'[0-9]', new_password):
            return jsonify(success=False, message="Password must be at least 8 characters long and include both letters and numbers."), 400

        try:
            with get_db_connection() as conn:
                cursor = conn.cursor()
                cursor.execute(
                    '''SELECT * FROM password_reset_tokens WHERE token = ? AND expires_at > ? AND used = 0''',
                    (token, datetime.now())
                )
                token_record = cursor.fetchone()

                if token_record:
                    # Update the user's password
                    password_hash = bcrypt.hashpw(new_password.encode('utf-8'), bcrypt.gensalt())
                    cursor.execute(
                        '''UPDATE users SET password_hash = ? WHERE id = ?''',
                        (password_hash, token_record['user_id'])
                    )
                    # Mark the token as used
                    cursor.execute('UPDATE password_reset_tokens SET used = 1 WHERE id = ?', (token_record['id'],))
                    conn.commit()

                    return jsonify(success=True, message="Password updated successfully.")
                else:
                    return jsonify(success=False, message="Invalid or expired token."), 400

        except sqlite3.Error as e:
            print(f"Database error: {e}")
            return jsonify(success=False, message="An internal error occurred. Please try again later."), 500

@app.route('/api/users', methods=['GET', 'POST'])
def manage_users():
    if request.method == 'GET':
        try:
            with get_db_connection() as conn:
                cursor = conn.cursor()
                cursor.execute('SELECT id, username, email, role, department FROM users')
                users = cursor.fetchall()
                return jsonify({"users": [
                    {
                        "id": user[0],
                        "username": user[1],
                        "email": user[2],
                        "role": user[3],
                        "department": user[4]
                    } for user in users
                ]})
        except sqlite3.Error as e:
            print(f"Database error: {e}")
            return jsonify({"error": "Unable to fetch users."}), 500
    
    elif request.method == 'POST':
        username = request.form.get('username')
        email = request.form.get('email')
        password = request.form.get('password')
        role = request.form.get('role', 'user')
        department = request.form.get('department')
        
        if not username or not email or not password or not department:
            return jsonify({"error": "All fields are required."}), 400
        result = email_manager.add_user(username, email)
        password_hash = bcrypt.hashpw(password.encode('utf-8'), bcrypt.gensalt())
        
        try:
            with get_db_connection() as conn:
                cursor = conn.cursor()
                cursor.execute(
                    'INSERT INTO users (username, email, password_hash, role, department) VALUES (?, ?, ?, ?, ?)', 
                    (username, email, password_hash, role, department)
                )
                conn.commit()
            return jsonify({"message": "User added successfully."}), 201
        except sqlite3.IntegrityError:
            return jsonify({"error": "Username or email already exists."}), 400
        except sqlite3.Error as e:
            print(f"Database error: {e}")
            return jsonify({"error": "Unable to add user."}), 500

@app.route('/api/users/<int:user_id>', methods=['DELETE'])
def delete_user(user_id):
    try:
        with get_db_connection() as conn:
            cursor = conn.cursor()
            
            # Fetch the username and email of the user to be deleted
            cursor.execute('SELECT username, email FROM users WHERE id = ?', (user_id,))
            user = cursor.fetchone()
            
            if not user:
                return jsonify({"error": "User not found."}), 404

            username, email = user

            # Delete the user from the email manager
            result = email_manager.delete_user( email)

            # Delete the user from the database
            cursor.execute('DELETE FROM users WHERE id = ?', (user_id,))
            conn.commit()

            return jsonify({"message": "User deleted successfully."}), 200
    except sqlite3.Error as e:
        print(f"Database error: {e}")
        return jsonify({"error": "Unable to delete user."}), 500

 
@app.route('/api/users/<int:user_id>', methods=['GET', 'PUT'])
def user_info(user_id):
    """Get and edit user info."""
    if request.method == 'GET':
        # Fetch the user info
        try:
            with get_db_connection() as conn:
                cursor = conn.cursor()
                cursor.execute("SELECT id, username, email, role, department FROM users WHERE id = ?", (user_id,))
                user = cursor.fetchone()
                
                if user:
                    return jsonify({"success": True, "user": {
                        "id": user[0],
                        "username": user[1],
                        "email": user[2],
                        "role": user[3],
                        "department": user[4]
                    }})

                else:
                    return jsonify({"success": False, "message": "User not found"}), 404
        except sqlite3.Error as e:
            print(f"Database error: {e}")
            return jsonify({"success": False, "message": "Database error occurred"}), 500

    if request.method == 'PUT':
        # Update the user info
        username = request.form.get('username')
        email = request.form.get('email')
        role = request.form.get('role')
        department = request.form.get('department')
        if not all([username, email, role, department]):
            return jsonify({"error": "All fields are required."}), 400
        result = email_manager.update_user(username, email)
        if not result:
            result = email_manager.add_user(username, email)      
        try:
            with get_db_connection() as conn:
                cursor = conn.cursor()
                cursor.execute("""
                    UPDATE users
                    SET username = ?, email = ?, role = ?, department = ?
                    WHERE id = ?
                """, (username, email, role, department, user_id))
                conn.commit()
            return jsonify({"success": True, "message": "User info updated successfully"})

        except sqlite3.Error as e:
            print(f"Error updating user info: {e}")
            return jsonify({"success": False, "message": "Failed to update user info"}), 500

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        login_identifier = request.form['login_identifier']
        password = request.form['password']
        
        with get_db_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('SELECT * FROM users WHERE username = ? OR email = ?', (login_identifier, login_identifier))
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

@app.route('/user-management')
def user_management():
    return render_template('user_management.html')

# Add this function to server.py
def add_department_column():
    try:
        with sqlite3.connect(DATABASE) as conn:
            cursor = conn.cursor()
            # Add department column if it doesn't exist
            cursor.execute('''
                PRAGMA foreign_keys=off;
                BEGIN TRANSACTION;
                ALTER TABLE users ADD COLUMN department TEXT;
                COMMIT;
                PRAGMA foreign_keys=on;
            ''')
            print("Successfully added department column")
    except sqlite3.Error as e:
        print(f"Database error: {e}")
        conn.rollback()


def get_local_ip():
    hostname = socket.gethostname()
    ip_address = socket.gethostbyname(hostname)
    return ip_address
# Call this function before running the app
if __name__ == '__main__':
    try:
        add_department_column()  # Add this line before init_db()
        init_db()
        ip_address = get_local_ip()
        # Show IP and message
        print(f"Your app is accessible at: http://{ip_address}:8181/")
        serve(app, host="0.0.0.0", port=8181, threads=100)  # Change `threads` to any number you need
    finally:
        scheduler.shutdown()
    