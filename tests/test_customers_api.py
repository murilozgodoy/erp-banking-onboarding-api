def test_create_customer_returns_201(client, sample_customer_payload):
    response = client.post("/customers", json=sample_customer_payload)
    assert response.status_code == 201
    body = response.json()
    assert body["id"] > 0
    assert body["cpf"] == sample_customer_payload["cpf"]
    assert body["address"]["cidade"] == "São Paulo"
    assert body["financial_profile"]["renda_mensal"] == 8000.0
    assert body["anamnesis"] is None


def test_create_customer_conflict_on_duplicate_cpf(client, sample_customer_payload):
    r1 = client.post("/customers", json=sample_customer_payload)
    assert r1.status_code == 201
    r2 = client.post("/customers", json=sample_customer_payload)
    assert r2.status_code == 409


def test_get_customer_returns_authorized_data(client, sample_customer_payload):
    created = client.post("/customers", json=sample_customer_payload).json()
    r = client.get(f"/customers/{created['id']}")
    assert r.status_code == 200
    assert r.json()["nome"] == sample_customer_payload["nome"]


def test_get_customer_not_found(client):
    r = client.get("/customers/9999")
    assert r.status_code == 404


def test_put_anamnesis_creates_then_updates(client, sample_customer_payload):
    customer = client.post("/customers", json=sample_customer_payload).json()

    r1 = client.put(
        f"/customers/{customer['id']}/anamnesis",
        json={"dividas_ativas": 1000.0, "comprometimento_renda": 20.0},
    )
    assert r1.status_code == 200
    assert r1.json()["dividas_ativas"] == 1000.0

    r2 = client.put(
        f"/customers/{customer['id']}/anamnesis",
        json={"dividas_ativas": 2500.0, "comprometimento_renda": 35.0},
    )
    assert r2.status_code == 200
    assert r2.json()["dividas_ativas"] == 2500.0
    assert r2.json()["comprometimento_renda"] == 35.0

    r3 = client.get(f"/customers/{customer['id']}")
    assert r3.json()["anamnesis"]["dividas_ativas"] == 2500.0


def test_put_anamnesis_customer_not_found(client):
    r = client.put(
        "/customers/9999/anamnesis",
        json={"dividas_ativas": 0.0, "comprometimento_renda": 0.0},
    )
    assert r.status_code == 404


def test_create_customer_invalid_payload(client):
    r = client.post("/customers", json={"nome": "X"})
    assert r.status_code == 422


def test_list_customers_empty(client):
    r = client.get("/customers")
    assert r.status_code == 200
    assert r.json() == []


def test_list_customers_newest_first_with_search(client, sample_customer_payload):
    client.post("/customers", json=sample_customer_payload)
    other = {**sample_customer_payload, "nome": "Maria Souza", "cpf": "98765432100"}
    client.post("/customers", json=other)

    all_customers = client.get("/customers").json()
    assert [c["nome"] for c in all_customers] == ["Maria Souza", "João da Silva"]
    assert all_customers[0]["financial_profile"]["renda_mensal"] == 8000.0

    assert [c["nome"] for c in client.get("/customers", params={"q": "maria"}).json()] == ["Maria Souza"]
    by_cpf = client.get("/customers", params={"q": "123.456"}).json()
    assert [c["cpf"] for c in by_cpf] == ["12345678900"]
    assert len(client.get("/customers", params={"limit": 1}).json()) == 1
    assert client.get("/customers", params={"limit": 1, "offset": 1}).json()[0]["nome"] == "João da Silva"


def test_list_customers_invalid_pagination(client):
    assert client.get("/customers", params={"limit": 0}).status_code == 422
    assert client.get("/customers", params={"offset": -1}).status_code == 422
