import win32com.client as win32
import pythoncom

class EmailNotifier:
    @staticmethod
    def send_task_notification(recipient_name, recipient_email, task_details):
        """
        Send an email notification about a task.

        Args:
            recipient_name (str): Name of the recipient
            recipient_email (str): Email address of the recipient
            task_details (dict): Dictionary containing task information
        """
        try:
            # Initialize COM libraries for multi-threaded application
            pythoncom.CoInitialize()

            # Create Outlook application
            outlook = win32.Dispatch('outlook.application')
            mail = outlook.CreateItem(0)  # 0 represents mail item

            # Construct email content
            mail.Subject = f"Task Update: {task_details.get('description', 'Unnamed Task')}"
            
            mail.Body = f"""
Dear {recipient_name},

Task Notification Details:
-------------------------
Description: {task_details.get('description', 'N/A')}
Priority: {task_details.get('priority', 'N/A')}
Status: {task_details.get('status', 'N/A')}
Assigned Person: {task_details.get('assigned_person', 'N/A')}
Due Date: {task_details.get('due_date', 'No due date')}
Completion: {task_details.get('percentage_completion', '0')}%

Please review and take necessary actions.

Best regards,
            """

            mail.To = recipient_email
            mail.Send()

            return True
        except Exception as e:
            print(f"Email sending error: {e}")
            return False
        finally:
            # Uninitialize COM libraries
            pythoncom.CoUninitialize()
