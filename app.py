from flask import Flask, render_template, request, redirect, url_for, jsonify
import sqlite3
import os
from datetime import datetime

app = Flask(__name__)
DATABASE = 'tasks.db'

def get_db_connection():
    """Establish a connection to the database."""
    conn = sqlite3.connect(DATABASE)
    conn.row_factory = sqlite3.Row  # Return results as dictionaries
    return conn

def init_db():
    """Initialize the database and create tables if they don't exist."""
    with sqlite3.connect(DATABASE) as conn:
        cursor = conn.cursor()
        
        # Tasks table (existing)
        cursor.execute('''
        CREATE TABLE IF NOT EXISTS tasks (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            description TEXT NOT NULL,
            priority TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'Open',
            percentage_completion INTEGER DEFAULT 0 CHECK(percentage_completion BETWEEN 0 AND 100),
            notes TEXT DEFAULT '',
            updates TEXT DEFAULT '',
            due_date TEXT DEFAULT NULL,
            monthly_action_id INTEGER,
            created_at TEXT DEFAULT (DATETIME('now', 'localtime')),
            FOREIGN KEY(monthly_action_id) REFERENCES monthly_action_items(id)
        )
        ''')

        # Monthly Action Items table (new)
        cursor.execute('''
        CREATE TABLE IF NOT EXISTS monthly_action_items (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            description TEXT NOT NULL,
            priority TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'Open',
            due_date TEXT DEFAULT NULL,
            notes TEXT DEFAULT '',
            percentage_completion INTEGER DEFAULT 0 CHECK(percentage_completion BETWEEN 0 AND 100),
            created_at TEXT DEFAULT (DATETIME('now', 'localtime'))
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
    """Render the home page with tasks and monthly action items."""
    try:
        with get_db_connection() as conn:
            cursor = conn.cursor()
            
            # Fetch tasks with their linked Monthly Action Item description
            cursor.execute("""
                SELECT 
                    tasks.id, tasks.description, tasks.priority, tasks.status, 
                    tasks.percentage_completion, tasks.notes, tasks.updates, 
                    tasks.due_date, monthly_action_items.description AS monthly_action_description
                FROM tasks
                LEFT JOIN monthly_action_items
                ON tasks.monthly_action_id = monthly_action_items.id
                WHERE tasks.status IN ('Open', 'In Progress')
            """)
            tasks = cursor.fetchall()
            print("Tasks:", tasks)  # Debug print
            
            # Fetch monthly action items for task creation dropdown
            cursor.execute("SELECT id, description, priority FROM monthly_action_items WHERE status IN ('Open', 'In Progress')")
            
            monthly_actions = cursor.fetchall()
            print("Monthly Actions:", monthly_actions)  # Debug print
        
        return render_template('home.html', tasks=tasks, monthly_actions=monthly_actions)
    except sqlite3.Error as e:
        print(f"Database error: {e}")
        return f"An error occurred: {e}", 500

# Modify add_task route to support monthly action item linking
@app.route('/add', methods=['POST'])
def add_task():
    """Add a new task with optional monthly action item link."""
    description = request.form.get('description', '').strip()
    priority = request.form.get('priority', 'Medium')
    due_date = request.form.get('due_date', '').strip()
    monthly_action_id = request.form.get('monthly_action_id')

    if not description:
        return "Error: Task description cannot be empty!", 400

    try:
        with sqlite3.connect(DATABASE) as conn:
            cursor = conn.cursor()
            cursor.execute("""
                INSERT INTO tasks (description, priority, due_date, status, monthly_action_id)
                VALUES (?, ?, ?, 'Open', ?)
            """, (description, priority, due_date, monthly_action_id))
            conn.commit()
        return redirect(url_for('home'))
    except sqlite3.Error as e:
        print(f"Database error: {e}")
        return "Error: Unable to add task to the database.", 500

@app.route('/update/<int:task_id>', methods=['POST'])
def update_task(task_id):
    """Update task details."""
    status = request.form.get('status', 'Open')
    percentage_completion = request.form.get('percentage_completion', '0').strip()
    notes = request.form.get('notes', '').strip()

    try:
        # Validate and convert percentage_completion to integer
        percentage_completion = int(percentage_completion)
        if not 0 <= percentage_completion <= 100:
            return "Error: Completion percentage must be between 0 and 100.", 400

        with sqlite3.connect(DATABASE) as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT updates FROM tasks WHERE id = ?", (task_id,))
            current_updates = cursor.fetchone()
            updates = current_updates[0] if current_updates else ""
            update_entry = (
                (current_updates[0] or '') 
                + f"\n\n== Update ({datetime.now().strftime('%Y-%m-%d %H:%M')})\n{notes or 'No notes'}Status: {status}\n"
            )
            #update_entry = f"Updated on {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}: {notes or 'No notes'}\n"
            new_updates = updates + update_entry

            cursor.execute("""
                UPDATE tasks SET status = ?, percentage_completion = ?, notes = ?, updates = ?
                WHERE id = ?
            """, (status, percentage_completion, notes, new_updates, task_id))
            conn.commit()
        return redirect(url_for('home'))
    except sqlite3.Error as e:
        print(f"Database error: {e}")
        return "Error: Unable to update task.", 500

@app.route('/delete/<int:task_id>', methods=['POST'])
def delete_task(task_id):
    """Delete a task."""
    try:
        with sqlite3.connect(DATABASE) as conn:
            cursor = conn.cursor()
            cursor.execute("DELETE FROM tasks WHERE id = ?", (task_id,))
            conn.commit()
        return redirect(url_for('home'))
    except sqlite3.Error as e:
        print(f"Database error: {e}")
        return "Error: Unable to delete task.", 500


@app.route('/fetch', methods=['GET'])
def fetch_tasks():
    """Fetch tasks based on filters."""
    status = request.args.get('status', '').strip()
    keyword = request.args.get('keyword', '').strip()

    try:
        with sqlite3.connect(DATABASE) as conn:
            cursor = conn.cursor()
            query = "SELECT id, description, status, notes, updates, created_at FROM tasks WHERE 1=1"
            params = []

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
                {"id": task[0], "description": task[1], "status": task[2], "notes": task[3], "updates": task[4], "created_at": task[5]}
                for task in tasks
            ]
        })
    except sqlite3.Error as e:
        print(f"Database error: {e}")
        return jsonify({"success": False, "error": "Unable to fetch tasks"}), 500

@app.route('/fetch_monthly_actions', methods=['GET'])
def fetch_actions():
    """Fetch monthly actions based on filters."""
    status = request.args.get('status', '').strip()
    keyword = request.args.get('keyword', '').strip()

    try:
        with sqlite3.connect(DATABASE) as conn:
            cursor = conn.cursor()
            query = """
                SELECT id, description, status, notes, due_date, 
                       percentage_completion, created_at 
                FROM monthly_action_items WHERE 1=1
            """
            params = []

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
    """Delete historical tasks."""
    status = request.form.get('status', '').strip()

    if not status:
        return jsonify({"success": False, "error": "Status is required to delete tasks."}), 400

    try:
        with sqlite3.connect(DATABASE) as conn:
            cursor = conn.cursor()
            cursor.execute("DELETE FROM tasks WHERE status = ?", (status,))
            conn.commit()
        return jsonify({"success": True, "message": f"Tasks with status '{status}' deleted."})
    except sqlite3.Error as e:
        print(f"Database error: {e}")
        return jsonify({"success": False, "error": "Unable to delete tasks."}), 500

@app.route('/monthly-action', methods=['GET', 'POST'])
def monthly_action():
    # ... (previous code remains the same)

    # Fetch existing monthly action items
    try:
        with sqlite3.connect(DATABASE) as conn:
            cursor = conn.cursor()
            cursor.execute('''
                SELECT id, description, priority, status, 
                       due_date, percentage_completion, notes
                FROM monthly_action_items
                WHERE status IN ('Open', 'In Progress')
                ORDER BY created_at DESC
            ''')
            monthly_actions = cursor.fetchall()
        return render_template('monthly_action.html', monthly_actions=monthly_actions)
    except sqlite3.Error as e:
        print(f"Database error: {e}")
        return "Error: Unable to fetch monthly action items.", 500
    # Fetch existing monthly action items
    try:
        with sqlite3.connect(DATABASE) as conn:
            cursor = conn.cursor()
            cursor.execute('''
                SELECT id, description, priority, status, 
                       due_date, percentage_completion, notes
                FROM monthly_action_items
                ORDER BY created_at DESC
            ''')
            monthly_actions = cursor.fetchall()
        return render_template('monthly_action.html', monthly_actions=monthly_actions)
    except sqlite3.Error as e:
        print(f"Database error: {e}")
        return "Error: Unable to fetch monthly action items.", 500
    
@app.route('/update_monthly_action/<int:action_id>', methods=['POST'])
def update_monthly_action(action_id):
    """Update a monthly action status."""
    status = request.form.get('status', 'Open')
    percentage_completion = request.form.get('percentage_completion', '0').strip()
    notes = request.form.get('notes', '').strip()

    try:
        percentage_completion = int(percentage_completion)
        if not 0 <= percentage_completion <= 100:
            return "Error: Completion percentage must be between 0 and 100.", 400

        with sqlite3.connect(DATABASE) as conn:
            cursor = conn.cursor()
            cursor.execute('''
                UPDATE monthly_action_items 
                SET status = ?, percentage_completion = ?, notes = ?
                WHERE id = ?
            ''', (status, percentage_completion, notes, action_id))
            conn.commit()
        return redirect(url_for('monthly_action'))
    except sqlite3.Error as e:
        print(f"Database error: {e}")
        return "Error: Unable to update monthly action item.", 500

@app.route('/delete_monthly_action/<int:action_id>', methods=['POST'])
def delete_monthly_action(action_id):
    """Delete a monthly action item."""
    try:
        with sqlite3.connect(DATABASE) as conn:
            cursor = conn.cursor()
            # First, remove any linked tasks
            cursor.execute("DELETE FROM tasks WHERE monthly_action_id = ?", (action_id,))
            # Then delete the monthly action item
            cursor.execute("DELETE FROM monthly_action_items WHERE id = ?", (action_id,))
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
    """Provide data for the monthly progress chart."""
    try:
        with sqlite3.connect(DATABASE) as conn:
            cursor = conn.cursor()
            
            # 1. Priority vs Completion Percentage
            cursor.execute('''
                SELECT priority, 
                       AVG(percentage_completion) AS avg_completion 
                FROM tasks 
                GROUP BY priority
            ''')
            priority_completion_data = cursor.fetchall()

            # 2. Monthly Progress for Tasks
            cursor.execute('''
                SELECT strftime('%Y-%m', due_date) AS month,
                       SUM(CASE WHEN status = 'Completed' THEN 1 ELSE 0 END) AS completed,
                       SUM(CASE WHEN status = 'In Progress' THEN 1 ELSE 0 END) AS in_progress,
                       SUM(CASE WHEN status = 'Open' THEN 1 ELSE 0 END) AS open
                FROM tasks 
                GROUP BY month
            ''')
            monthly_task_progress = cursor.fetchall()
            
            # 3. Monthly Progress for Action Items
            cursor.execute('''
                SELECT strftime('%Y-%m', due_date) AS month,
                       SUM(CASE WHEN status = 'Completed' THEN 1 ELSE 0 END) AS completed,
                       SUM(CASE WHEN status = 'In Progress' THEN 1 ELSE 0 END) AS in_progress,
                       SUM(CASE WHEN status = 'Open' THEN 1 ELSE 0 END) AS open
                FROM monthly_action_items 
                GROUP BY month
            ''')
            monthly_action_progress = cursor.fetchall()
            
            # 4. Action Item Status Breakdown
            cursor.execute('''
                SELECT status, COUNT(*) AS count
                FROM monthly_action_items
                GROUP BY status
            ''')
            action_status_data = cursor.fetchall()
            status_breakdown = {row[0]: row[1] for row in action_status_data}

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
                "status_breakdown": status_breakdown
            })
    except sqlite3.Error as e:
        print(f"Database error: {e}")
        return jsonify({"error": "Failed to fetch progress data."}), 500

@app.route('/task_charts')
def task_charts():
    """Render the Task Progress Charts page."""
    return render_template('task_charts.html')

 
@app.route('/task-data', methods=['GET'])
def task_data():
    """Provide task data for charts and progress bars."""
    try:
        with sqlite3.connect(DATABASE) as conn:
            cursor = conn.cursor()

            # Fetch tasks with name, priority, progress, and due date
            cursor.execute('''
                SELECT 
                    description AS name, 
                    priority, 
                    percentage_completion AS progress, 
                    due_date 
                FROM tasks
                WHERE status IN ('Open', 'In Progress', 'Completed')
            ''')
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
            "priorities": [task[1] for task in tasks],
            "progress": [task[2] for task in tasks],
        }

        return jsonify(task_data)
    except sqlite3.Error as e:
        print(f"Database error: {e}")
        return jsonify({"error": "Failed to fetch task data."}), 500


if __name__ == '__main__':
    init_db()
    app.run(host="0.0.0.0", port=8181, threaded=True, use_reloader=False)
