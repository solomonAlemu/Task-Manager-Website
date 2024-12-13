import win32com.client as win32
import pythoncom

class EmailNotifier:
    @staticmethod
    def send_task_notification(recipient_list, task_details):
        """
        Send an email notification about a task to multiple recipients.

        Args:
            recipient_list (list): List of dictionaries with recipient 'name' and 'email'
            task_details (dict): Dictionary containing task information
        """
        try:
            pythoncom.CoInitialize()

            outlook = win32.Dispatch('outlook.application')
            mail = outlook.CreateItem(0)

            # Generate the salutation
            recipient_names = [recipient['name'] for recipient in recipient_list]
            salutation = f"Dear {', '.join(recipient_names[:-1])} & {recipient_names[-1]}," if len(recipient_names) > 1 else f"Dear {recipient_names[0]},"

            # Construct the email body
            mail.Subject = f"Task Update: {task_details.get('description', 'Unnamed Task')}"
            mail.Body = f"""{salutation}
Greetings!

Please review and take necessary actions.

    Task Notification Details:
    -------------------------
    Description: {task_details.get('description', 'N/A')}
    Priority: {task_details.get('priority', 'N/A')}
    Status: {task_details.get('status', 'N/A')}
    Assigned Person: {task_details.get('assigned_person', 'N/A')}
    Due Date: {task_details.get('due_date', 'No due date')}
    Completion: {task_details.get('percentage_completion', '0')}%

Best regards,
Your Team
            """

            # Add all recipient emails to the "To" field
            mail.To = "; ".join([recipient['email'] for recipient in recipient_list])
            mail.Send()

            return True
        except Exception as e:
            print(f"Email sending error: {e}")
            return False
        finally:
            pythoncom.CoUninitialize()
