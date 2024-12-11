document.addEventListener("DOMContentLoaded", () => {
  const taskForm = document.getElementById("taskForm");
  const tasksContainer = document.getElementById("tasks");

  let tasks = [];

  // Render tasks
  function renderTasks() {
    tasksContainer.innerHTML = "";

    tasks.forEach((task, index) => {
      const taskEl = document.createElement("div");
      taskEl.className = "task-item";

      taskEl.innerHTML = `
        <div class="task-item-header">
          <strong>${task.title}</strong>
          <span class="task-status">[${task.status}]</span>
        </div>
        <p>${task.notes || "No additional notes."}</p>
        <p><strong>Due:</strong> ${task.dueDate || "No due date"}</p>
        <div class="task-actions">
          <button class="edit-btn" onclick="editTask(${index})">Edit</button>
          <button class="delete-btn" onclick="deleteTask(${index})">Delete</button>
          <button onclick="updateStatus(${index})">Next Status</button>
        </div>
      `;

      tasksContainer.appendChild(taskEl);
    });
  }

  // Add new task
  taskForm.addEventListener("submit", (e) => {
    e.preventDefault();
    const title = document.getElementById("taskTitle").value.trim();
    const notes = document.getElementById("taskNotes").value.trim();
    const dueDate = document.getElementById("taskDueDate").value;

    if (title) {
      tasks.push({
        title,
        notes,
        dueDate,
        status: "Open",
      });

      taskForm.reset();
      renderTasks();
    }
  });

  // Delete task
  window.deleteTask = function (index) {
    tasks.splice(index, 1);
    renderTasks();
  };

  // Edit task
  window.editTask = function (index) {
    const task = tasks[index];
    document.getElementById("taskTitle").value = task.title;
    document.getElementById("taskNotes").value = task.notes;
    document.getElementById("taskDueDate").value = task.dueDate;

    tasks.splice(index, 1); // Remove the old task to replace it
    renderTasks();
  };

  // Update status
  window.updateStatus = function (index) {
    const statuses = ["Open", "In Progress", "Closed"];
    const task = tasks[index];
    const currentStatusIndex = statuses.indexOf(task.status);
    task.status = statuses[(currentStatusIndex + 1) % statuses.length];
    renderTasks();
  };

  renderTasks();
});
