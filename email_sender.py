import win32com.client as win32
import pythoncom

class EmailNotifier:
    @staticmethod
    def send_task_notification(recipient_list, task_details, email_intent):
        """
        Send an email notification about a task to multiple recipients.
    
        Args:
            recipient_list (list): List of dictionaries with recipient 'name' and 'email'.
            task_details (dict): Dictionary containing task information.
            email_intent (str): The intent of the email (e.g., 'Assignment', 'Reminder', etc.).
        Returns:
            bool: True if the email was sent successfully, False otherwise.
        """
        try:
            pythoncom.CoInitialize()

            outlook = win32.Dispatch('outlook.application')
            mail = outlook.CreateItem(0)

            # Generate the salutation
            recipient_names = [recipient['name'] for recipient in recipient_list]
            salutation = f"Dear {', '.join(recipient_names[:-1])} & {recipient_names[-1]}," if len(recipient_names) > 1 else f"Dear {recipient_names[0]},"

            # Construct the email body based on intent
            if email_intent == "Assignment":
                body = f"""{salutation}
Greetings!

You have been assigned a new task:

    Description: {task_details.get('description', 'N/A')}
    Priority: {task_details.get('priority', 'N/A')}
    Due Date: {task_details.get('due_date', 'No due date')}

Please take necessary actions.

Best regards,
Your Team
                """
            elif email_intent == "Status request":
                body = f"""{salutation}
Greetings!

I kindly request a status update for the following task:

    Description: {task_details.get('description', 'N/A')}
    Priority: {task_details.get('priority', 'N/A')}
    Assigned Person: {task_details.get('assigned_person', 'N/A')}
    Due Date: {task_details.get('due_date', 'No due date')}

Please provide an update at your earliest convenience.

Best regards,
Your Team
                """
            elif email_intent == "Reminder":
                body = f"""{salutation}
Greetings!

This is a reminder for the following task:

    Description: {task_details.get('description', 'N/A')}
    Priority: {task_details.get('priority', 'N/A')}
    Due Date: {task_details.get('due_date', 'No due date')}

Please ensure timely completion.

Best regards,
Your Team
                """
            elif email_intent == "Notification":
                body = f"""{salutation}
Greetings!

Here is an update regarding the following task:

    Description: {task_details.get('description', 'N/A')}
    Priority: {task_details.get('priority', 'N/A')}
    Status: {task_details.get('status', 'N/A')}
    Completion: {task_details.get('percentage_completion', '0')}%

Thank you for your attention.

Best regards,
Your Team
                """
            else:
                body = f"{salutation}\n\nNo specific intent provided for this email."

            mail.Subject = f"{email_intent}: {task_details.get('description', 'Unnamed Task')}"
            mail.Body = body
            mail.To = "; ".join([recipient['email'] for recipient in recipient_list])
            mail.Send()

            return True
        except Exception as e:
            print(f"Email sending error: {e}")
            return False
        finally:
            pythoncom.CoUninitialize()
    @staticmethod
    def send_password_reset_email(recipient_email, subject, email_body):
        """
        Send a password reset email to the specified recipient.

        Args:
            recipient_email (str): The email address of the recipient.
            subject (str): The subject of the email.
            email_body (str): The body of the email.
        
        Returns:
            bool: True if the email was sent successfully, False otherwise.
        """
        try:
            pythoncom.CoInitialize()

            outlook = win32.Dispatch('outlook.application')
            mail = outlook.CreateItem(0)

            # Construct the email
            salutation = "Dear User,"
            mail.Body = f"""{salutation}
Greetings!

{email_body}

Best regards,
Your Task Manager
            """

            mail.Subject = subject
            mail.To = recipient_email
            mail.Send()

            return True
        except Exception as e:
            print(f"Email sending error: {e}")
            return False
        finally:
            pythoncom.CoUninitialize()
