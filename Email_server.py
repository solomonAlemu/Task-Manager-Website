import os
import win32com.client as win32
import pythoncom
import pandas as pd


def extract_username(email):
    """Extracts the username from an email address."""
    if "@" in email:
        username = email.split("@")[0]
        return username
    else:
        raise ValueError("Invalid email address")
    
class EmailSender:
    def __init__(self):
        self.outlook = win32.Dispatch("Outlook.Application")

    def send_email_with_attachment(self, recipient_email,user_name,  file_path, tails):
        try:
            email = self.outlook.CreateItem(0)
            username = user_name
            subject = f"Overdue Tasks Report for: {', '.join(tails)}"
            body = f"Dear {username},\nGreetings,\n\nPlease find the attached file containing the overdue tasks for {', '.join(tails)}.\n\nThankfully,"

            email.Subject = subject
            email.To = recipient_email
            email.Body = body  

            # Debugging: Print the path to be attached
            print(f"Attempting to attach file: {file_path}")
            if os.path.exists(file_path):
                print("Attachment exists, proceeding to send email.")
                email.Attachments.Add(file_path)
            else:
                print(f"File does not exist: {file_path}")
                return
            
            email.Send()
            print(f"Email sent to {recipient_email} with subject '{subject}'")
        except Exception as e:
            print(f"Failed to send email: {str(e)}")

if __name__ == "__main__":
    pythoncom.CoInitialize()
    email_sender = EmailSender()
    
    recipient = "solomonal@ethiopianairlines.com"
    tails = ["Tail1", "Tail2"]

    # Use absolute path for the folder
    folder_path = os.path.abspath('output/')  # Get absolute path
    os.makedirs(folder_path, exist_ok=True)
    
    # Sample data to ensure the CSV is created
    data = [["Aircraft1", "TaskType1", "Task1", "Barcode1", "DueDate1"],
            ["Aircraft2", "TaskType2", "Task2", "Barcode2", "DueDate2"]]
    
    file_path = os.path.join(folder_path, "output.csv")
    new_data = pd.DataFrame(data, columns=["Aircraft", "Overdue Task Type", "Overdue Tasks", "Task Barcode", "Due"])
    
    new_data.to_csv(file_path, index=False)
    print(f"CSV file created: {file_path}")  # Check if the file is created
    
    # Check current working directory
    print(f"Current working directory: {os.getcwd()}")

    # Send the email
    email_sender.send_email_with_attachment(recipient, file_path, tails)

    pythoncom.CoUninitialize()
