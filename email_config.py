import json
import os

class EmailManager:
    def __init__(self, config_file='email_config.json'):
        self.config_file = config_file
        self.config = self.load_config()

    def load_config(self):
        """Load email configuration from JSON file."""
        if not os.path.exists(self.config_file):
            return {"users": []}
        
        with open(self.config_file, 'r') as f:
            return json.load(f)

    def save_config(self):
        """Save email configuration to JSON file."""
        with open(self.config_file, 'w') as f:
            json.dump(self.config, f, indent=4)

    def add_user(self, name, email):
        """Add a new user to the email configuration."""
        user = {
            "name": name,
            "email": email
        }
        
        # Check for duplicates
        if not any(u['email'] == email for u in self.config['users']):
            self.config['users'].append(user)
            self.save_config()
            return True
        return False

    def get_users(self):
        """Retrieve all users."""
        return self.config['users']

    def get_user_by_email(self, email):
        """Get a specific user by email."""
        return next((user for user in self.config['users'] if user['email'] == email), None)

    def update_user(self, email, new_name=None, new_email=None):
        """Update user details."""
        for user in self.config['users']:
            if user['email'] == email:
                if new_name:
                    user['name'] = new_name
                if new_email:
                    user['email'] = new_email
                self.save_config()
                return True
        return False

    def delete_user(self, email):
        """Remove a user from the configuration."""
        self.config['users'] = [user for user in self.config['users'] if user['email'] != email]
        self.save_config()
