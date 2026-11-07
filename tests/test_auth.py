import pytest
import json
import datetime
from app import app as flask_app_module
from models import db, User, PasswordResetToken

@pytest.fixture(scope="module")
def test_client():
    flask_app_module.config["TESTING"] = True
    flask_app_module.config["RATELIMIT_ENABLED"] = False
    with flask_app_module.test_client() as client:
        with flask_app_module.app_context():
            from init_db import init_and_seed_database
            init_and_seed_database()
            yield client

def test_login_success(test_client):
    user = User.query.filter_by(email="admin@opsflow.io").first()
    assert user is not None
    
    response = test_client.post("/api/v1/auth/login", json={"email": "admin@opsflow.io", "password": "AdminSecure2026!"})
    assert response.status_code == 200
    data = response.get_json()
    assert data["success"] is True
    assert data["user"]["email"] == "admin@opsflow.io"

def test_password_reset_flow(test_client):
    user = User.query.filter_by(email="admin@opsflow.io").first()
    assert user is not None
    
    # Request reset token
    resp1 = test_client.post("/api/v1/auth/forgot-password", json={"email": user.email})
    assert resp1.status_code == 200
    data1 = resp1.get_json()
    assert "dev_token" in data1
    token = data1["dev_token"]
    
    # Use token to reset password
    resp2 = test_client.post("/api/v1/auth/reset-password", json={
        "token": token,
        "new_password": "NewPassword123!"
    })
    assert resp2.status_code == 200
    data2 = resp2.get_json()
    assert data2["success"] is True
    
    # Check new password works
    resp3 = test_client.post("/api/v1/auth/login", json={"email": user.email, "password": "NewPassword123!"})
    assert resp3.status_code == 200
    
    # Re-use token fails
    resp4 = test_client.post("/api/v1/auth/reset-password", json={
        "token": token,
        "new_password": "AnotherPassword123!"
    })
    assert resp4.status_code == 400

    # Reset back to original to keep other tests working
    test_client.post("/api/v1/auth/forgot-password", json={"email": user.email})
    token_reset = test_client.post("/api/v1/auth/forgot-password", json={"email": user.email}).get_json()["dev_token"]
    test_client.post("/api/v1/auth/reset-password", json={"token": token_reset, "new_password": "AdminSecure2026!"})

def test_expired_reset_token(test_client):
    user = User.query.filter_by(email="admin@opsflow.io").first()
    
    resp1 = test_client.post("/api/v1/auth/forgot-password", json={"email": user.email})
    token = resp1.get_json()["dev_token"]
    
    # Manually expire it
    import hashlib
    token_hash = hashlib.sha256(token.encode("utf-8")).hexdigest()
    rec = PasswordResetToken.query.filter_by(token_hash=token_hash).first()
    rec.expires_at = datetime.datetime.utcnow() - datetime.timedelta(hours=2)
    db.session.commit()
    
    resp2 = test_client.post("/api/v1/auth/reset-password", json={
        "token": token,
        "new_password": "NewPassword123!"
    })
    assert resp2.status_code == 400
    assert "expired" in resp2.get_json()["error"].lower()

def test_unauthenticated_workflow_loading(test_client):
    test_client.get("/api/v1/auth/logout")
    resp = test_client.get("/api/v1/rules")
    assert resp.status_code == 401

def test_authenticated_workflow_loading(test_client):
    user = User.query.filter_by(email="admin@opsflow.io").first()
    test_client.post("/api/v1/auth/login", json={"email": user.email, "password": "AdminSecure2026!"})
    
    resp = test_client.get("/api/v1/rules")
    assert resp.status_code == 200
    assert "rules" in resp.get_json()
