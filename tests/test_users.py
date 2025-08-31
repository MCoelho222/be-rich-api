def test_read_users(client):
    response = client.get("/users/")
    assert response.status_code == 200
    assert isinstance(response.json(), list)
    assert len(response.json()) > 0


def test_create_user(client):
    response = client.post("/users/", json={
        "name": "New User",
        "email": "newuser@example.com",
        "password": "newpassword"
    })
    assert response.status_code == 201
    assert response.json()["name"] == "New User"
    assert response.json()["email"] == "newuser@example.com"


def test_update_user(client):
    # Get the list of users to retrieve a valid UUID
    response = client.get("/users/")
    assert response.status_code == 200
    users = response.json()
    assert len(users) > 0
    user_id = users[0]["id"]

    # Update the user using the retrieved UUID
    response = client.put(f"/users/{user_id}", json={
        "name": "Updated User",
        "email": "updateduser@example.com",
        "password": "updatedpassword"
    })

    assert response.status_code == 200
    assert response.json()["name"] == "Updated User"
    assert response.json()["email"] == "updateduser@example.com"


def test_read_user(client):
    # Get the list of users to retrieve a valid UUID
    response = client.get("/users/")
    assert response.status_code == 200
    users = response.json()
    assert len(users) > 0
    user_id = users[0]["id"]

    # Read the user using the retrieved UUID
    response = client.get(f"/users/{user_id}")
    assert response.status_code == 200
    assert response.json()["id"] == user_id