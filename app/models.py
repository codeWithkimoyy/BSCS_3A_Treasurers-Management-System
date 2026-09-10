from flask_login import UserMixin


class User(UserMixin):
    def __init__(self, id, username, role, display_name=None, email=None, picture=None):
        self.id = id
        self.username = username
        self.role = role
        self.display_name = display_name or username
        self.email = email
        self.picture = picture
