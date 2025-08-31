from datetime import datetime

def test_read_entries(client):
    response = client.get("/entries/")
    assert response.status_code == 200
    assert isinstance(response.json(), list)


def test_create_entry(client):
    response = client.post("/entries/", json={
        "amount": 100.0,
        "entry_type": "Income",
        "fixed": False,
        "installments": 1,
        "payment_method": "Pix",
        "category": "Energy",
        "description": "Test entry",
        "source": "Marcelo",
        "created_at": datetime.now().isoformat()
    })
    assert response.status_code == 201
    assert response.json()["amount"] == 100.0
    assert response.json()["entry_type"] == "Income"
    assert response.json()["description"] == "Test entry"


def test_update_entry(client):
    # Get the list of entries to retrieve a valid UUID
    response = client.get("/entries/")
    assert response.status_code == 200
    entries = response.json()
    assert len(entries) > 0
    entry_id = entries[0]["id"]

    # Update the entry using the retrieved UUID
    response = client.put(f"/entries/{entry_id}", json={
        "amount": 150.0,
        "entry_type": "Expense",
        "fixed": True,
        "installments": 2,
        "payment_method": "NU",
        "category": "Car",
        "description": "Updated entry",
        "source": "Marcelo",
        "created_at": datetime.now().isoformat()
    })

    assert response.status_code == 200
    assert response.json()["amount"] == 150.0
    assert response.json()["entry_type"] == "Expense"
    assert response.json()["description"] == "Updated entry"


def test_delete_entry(client):
    # Get the list of entries to retrieve a valid UUID
    response = client.get("/entries/")
    assert response.status_code == 200
    entries = response.json()
    assert len(entries) > 0
    entry_id = entries[0]["id"]

    # Delete the entry using the retrieved UUID
    response = client.delete(f"/entries/{entry_id}")
    assert response.status_code == 200

    # Verify the entry has been deleted
    response = client.get(f"/entries/{entry_id}")
    assert response.status_code == 404