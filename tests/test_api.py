import pandas as pd
import pytest

from src import MovieStorage
import main


def test_movies_persist(client, test_storage, uploaded_movies):
    other = MovieStorage(test_storage.db_path)

    df = other.get()
    assert other.count_movies() == 20
    assert len(df) == 20
    assert list(df.columns) == ["title", "release_year", "rating", "genre"]

    expected_titles = pd.read_csv("fixtures/sample_movies.csv")["title"].tolist()
    assert df["title"].tolist() == expected_titles

    storage_ids = [row["id"] for row in other.select_columns(["title"], limit=100)]
    response = client.get("/movies", params={"limit": 100})
    assert response.status_code == 200
    api_ids = [row["id"] for row in response.json()["data"]]

    assert storage_ids == list(range(1, 21))
    assert api_ids == list(range(1, 21))


def test_cache_and_processing(client, uploaded_movies, processing_body):
    # 1. First requests miss the cache and get stored in it
    for limit in (100, 1):
        response = client.get("/movies", params={"limit": limit})
        assert response.status_code == 200
        assert main.cache.get(limit) == response.json()

    # 2. Repeat limit=100: same response, now served from the cache
    first = main.cache.get(100)
    response = client.get("/movies", params={"limit": 100})
    assert response.status_code == 200
    assert response.json() == first

    # 3. Process: 20 -> 16 rows, cache cleared
    response = client.post("/movies/process", json=processing_body)
    assert response.status_code == 200
    report = response.json()
    assert report["validation_rows_removed"] == 0
    assert report["cleaning_report"]["rows_before"] == 20
    assert report["cleaning_report"]["rows_after"] == 16
    assert main.cache.get(100) is None
    assert main.cache.get(1) is None

    # 4. Retrieve again: fresh data from SQLite, then cached
    response = client.get("/movies", params={"limit": 100})
    assert response.status_code == 200
    body = response.json()
    assert body["total_rows"] == 16
    assert [row["title"] for row in body["data"]] == [f"Movie {c}" for c in "ABCDEFGHIJKLMNOP"]
    assert [row["id"] for row in body["data"]] == list(range(1, 17))
    assert main.cache.get(100) == body


def test_cache_hit_skips_database(client, uploaded_movies, monkeypatch):
    # 1. Populate the cache
    first = client.get("/movies", params={"limit": 100})
    assert first.status_code == 200

    # 2. Make any database call fail the test
    def fail(*args, **kwargs):
        pytest.fail("Database was called on a cache hit")

    monkeypatch.setattr(main.storage, "select_columns", fail)
    monkeypatch.setattr(main.storage, "count_movies", fail)

    # 3. Same request must be answered from the cache
    second = client.get("/movies", params={"limit": 100})
    assert second.status_code == 200
    assert second.json() == first.json()
