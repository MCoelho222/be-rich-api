def test_read_entries(client):
    response = client.get("/entries/")
    assert response.status_code == 200
    assert isinstance(response.json(), list)