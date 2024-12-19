# Task Manager Website

The Task Management System is a robust, web-based platform designed specifically for the AEP management team to streamline task tracking and management. Inspired by an Excel-based tool developed under the guidance of the former Director of AEP, @Zinaw, this application modernizes the approach by incorporating advanced features and a user-friendly interface. Reflecting on the limitations of Excel, this system offers a more dynamic and scalable solution. It enables efficient creation, delegation, and monitoring of tasks and action items with real-time updates and progress tracking.

## WHAT IT DOES

- **Comprehensive Planning:** Facilitates the creation and tracking of yearly, semi-annual, and monthly action plans.
- **Task Assignment:** Supports daily and long-term task assignments, ensuring alignment with overarching action items.
- **Progress Tracking:** Monitors execution status with deadlines and visual progress charts.

## Features

- **User Authentication:** Secure user registration and login system to protect personal task data.
- **Task Management:** Create, edit, and delete tasks with details such as descriptions, due dates, priorities, and statuses.
- **Email Notifications:** Send email notifications related to tasks, including assignments, status requests, reminders, and general notifications.
- **Responsive Design:** Optimized for various devices and screen sizes to ensure a seamless user experience.
- **Data Export and Analysis:** Export tasks and actions as CSV files based on selected date ranges, and generate visual insights with charts for priority vs. completion rates, task timelines, and action item breakdowns.
- **Dynamic Dashboard:** View detailed progress with interactive charts, including priority breakdowns and completion trends.

## Technologies Used

- **Frontend:**
  - HTML
  - CSS
  - JavaScript
- **Backend:**
  - Python
  - Flask
- **Database:**
  - SQLite
- **Visualization:**
  - Chart.js

## Installation

Follow these steps to set up the project locally:

1. **Clone the repository:**
   ```bash
   git clone https://github.com/solomonAlemu/Task-Manager-Website.git
   cd Task-Manager-Website
   ```
2. **Install dependencies:**
   ```bash
   pip install -r requirements.txt
   ```
3. **Set up the database:**
   ```bash
   flask db upgrade
   ```
4. **Run the application:**
   ```bash
   flask run
   ```
5. **Access the application:**
   Open your web browser and navigate to `http://127.0.0.1:5000`.

## Future Improvements

- **API Integration:** Support for third-party integrations (e.g., email clients, project management tools).
- **Mobile App:** A dedicated mobile application for on-the-go task management.
- **Advanced Analytics:** Predictive insights based on historical task data.

## Contributing

We welcome contributions! Please fork the repository and submit a pull request with your changes. For major changes, please open an issue to discuss your proposed modifications.

## License

This project is licensed under the MIT License. See the LICENSE file for details.

