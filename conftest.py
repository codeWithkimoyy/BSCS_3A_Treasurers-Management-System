import mongomock
import pytest
from werkzeug.security import generate_password_hash

import app.db as db_module
from app import create_app

# Patch the MongoClient reference used by app.db before the app connects.
db_module.MongoClient = mongomock.MongoClient


@pytest.fixture
def app():
    application = create_app({
        'TESTING': True,
        'SECRET_KEY': 'test-secret',
        'MONGO_URI': 'mongodb://localhost:27017/test_treasury',
    })
    # mongomock keeps a shared in-memory store; reset collections for isolation
    with application.app_context():
        from app.db import db as database
        for name in database.list_collection_names():
            database.drop_collection(name)
    return application


@pytest.fixture
def client(app):
    return app.test_client()


@pytest.fixture
def db(app):
    from app.db import db as database
    return database
